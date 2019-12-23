from typing import Dict, Optional, List, Any
from overrides import overrides
import torch
from torch.nn.modules.linear import Linear
from allennlp.common.checks import ConfigurationError
from allennlp.data import Vocabulary
from allennlp.modules import TimeDistributed, TextFieldEmbedder
from allennlp.models.model import Model
from allennlp.nn import InitializerApplicator, RegularizerApplicator
import allennlp.nn.util as util
from allennlp.training.metrics import CategoricalAccuracy, SpanBasedF1Measure
import torch.nn.functional as F
import torch.nn as nn
from modules import tch_layer

@Model.register("TCN")
class TcnTagger(Model):
    """
    Parameters
    ----------
    vocab : ``Vocabulary``, required
        A Vocabulary, required in order to compute sizes for input/output projections.
    text_field_embedder : ``TextFieldEmbedder``, required
        Used to embed the tokens ``TextField`` we get as input to the model.
    label_namespace : ``str``, optional (default=``labels``)
        This is needed to compute the SpanBasedF1Measure metric.
        Unless you did something unusual, the default value should be what you want.
    label_encoding : ``str``, optional (default=``None``)
        Label encoding to use when calculating span f1 and constraining
        the CRF at decoding time . Valid options are "BIO", "BIOUL", "IOB1", "BMES".
        Required if ``calculate_span_f1`` or ``constrain_crf_decoding`` is true.
    include_start_end_transitions : ``bool``, optional (default=``True``)
        Whether to include start and end transition parameters in the CRF.
    constrain_crf_decoding : ``bool``, optional (default=``None``)
        If ``True``, the CRF is constrained at decoding time to
        produce valid sequences of tags. If this is ``True``, then
        ``label_encoding`` is required. If ``None`` and
        label_encoding is specified, this is set to ``True``.
        If ``None`` and label_encoding is not specified, it defaults
        to ``False``.
    calculate_span_f1 : ``bool``, optional (default=``None``)
        Calculate span-level F1 metrics during training. If this is ``True``, then
        ``label_encoding`` is required. If ``None`` and
        label_encoding is specified, this is set to ``True``.
        If ``None`` and label_encoding is not specified, it defaults
        to ``False``.
    dropout:  ``float``, optional (default=``None``)
    verbose_metrics : ``bool``, optional (default = False)
        If true, metrics will be returned per label class in addition
        to the overall statistics.
    initializer : ``InitializerApplicator``, optional (default=``InitializerApplicator()``)
        Used to initialize the model parameters.
    regularizer : ``RegularizerApplicator``, optional (default=``None``)
        If provided, will be used to calculate the regularization penalty during training.
    """

    def __init__(
        self,
        vocab: Vocabulary,
        text_field_embedder: TextFieldEmbedder,
        label_namespace: str = "labels",
        label_encoding: Optional[str] = None,
        include_start_end_transitions: bool = True,
        calculate_span_f1: bool = None,
        dropout: Optional[float] = None,
        tcn_level: Optional[int] = None,
        tcn_input_size: Optional[int] = None,
        kernel_size: Optional[int] = None,
        tcn_hidden_size: Optional[int] = None,
        verbose_metrics: bool = False,
        initializer: InitializerApplicator = InitializerApplicator(),
        regularizer: Optional[RegularizerApplicator] = None,
    ) -> None:
        super().__init__(vocab, regularizer)

        self.label_namespace = label_namespace
        self.text_field_embedder = text_field_embedder
        self.num_tags = self.vocab.get_vocab_size(label_namespace)
        self._verbose_metrics = verbose_metrics
        if dropout:
            self.dropout = torch.nn.Dropout(dropout)
        else:
            self.dropout = None
        self.tcn_level = tcn_level
        self.tcn_input_size = tcn_input_size
        self.kernel_size = kernel_size
        self.tcn_hidden_size = tcn_hidden_size
        self.num_channels = [self.tcn_hidden_size] * self.tcn_level

        self.tag_projection_layer = TimeDistributed(Linear(self.tcn_hidden_size, self.num_tags))

        if calculate_span_f1 is None:
            calculate_span_f1 = label_encoding is not None

        self.label_encoding = label_encoding

        self.include_start_end_transitions = include_start_end_transitions

        self.tcn = tch_layer.TemporalConvNet(self.tcn_input_size, self.num_channels, kernel_size, dropout=dropout)

        self.metrics = {
            "accuracy": CategoricalAccuracy(),
            "accuracy3": CategoricalAccuracy(top_k=3),
        }
        self.calculate_span_f1 = calculate_span_f1
        if calculate_span_f1:
            if not label_encoding:
                raise ConfigurationError(
                    "calculate_span_f1 is True, but " "no label_encoding was specified."
                )
            self._f1_metric = SpanBasedF1Measure(
                vocab, tag_namespace=label_namespace, label_encoding=label_encoding
            )
        initializer(self)

    @overrides
    def forward(
        self,  # type: ignore
        tokens: Dict[str, torch.LongTensor],
        tags: torch.LongTensor = None,
        metadata: List[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, torch.Tensor]:

        """
        Parameters
        ----------
        tokens : ``Dict[str, torch.LongTensor]``, required
            The output of ``TextField.as_array()``, which should typically be passed directly to a
            ``TextFieldEmbedder``. This output is a dictionary mapping keys to ``TokenIndexer``
            tensors.  At its most basic, using a ``SingleIdTokenIndexer`` this is: ``{"tokens":
            Tensor(batch_size, num_tokens)}``. This dictionary will have the same keys as were used
            for the ``TokenIndexers`` when you created the ``TextField`` representing your
            sequence.  The dictionary is designed to be passed directly to a ``TextFieldEmbedder``,
            which knows how to combine different word representations into a single vector per
            token in your input.
        tags : ``torch.LongTensor``, optional (default = ``None``)
            A torch tensor representing the sequence of integer gold class labels of shape
            ``(batch_size, num_tokens)``.
        metadata : ``List[Dict[str, Any]]``, optional, (default = None)
            metadata containg the original words in the sentence to be tagged under a 'words' key.
        Returns
        -------
        An output dictionary consisting of:
        logits : ``torch.FloatTensor``
            The logits that are the output of the ``tag_projection_layer``
        mask : ``torch.LongTensor``
            The text field mask for the input tokens
        tags : ``List[List[int]]``
            The predicted tags using the Viterbi algorithm.
        loss : ``torch.FloatTensor``, optional
            A scalar loss to be optimised. Only computed if gold label ``tags`` are provided.
        """
        embedded_text_input = self.text_field_embedder(tokens)
        mask = util.get_text_field_mask(tokens)
        if self.dropout:
            embedded_text_input = self.dropout(embedded_text_input)

        output = self.tcn(embedded_text_input.transpose(1, 2)).transpose(1, 2)

        # 将每个token维度映射到tags的维度
        logits = self.tag_projection_layer(output)

        predicted_tags = torch.argmax(F.softmax(logits, dim=-1), dim=-1)

        output = {"logits": logits, "mask": mask, "tags": predicted_tags}

        if tags is not None:
            # cross entropy loss
            loss = nn.CrossEntropyLoss()
            output["loss"] = loss(logits.view(logits.shape[0]*logits.shape[1], -1), tags.view(tags.shape[0]*tags.shape[1]))

            # Represent viterbi tags as "class probabilities" that we can
            # feed into the metrics
            class_probabilities = logits * 0.0
            for i, instance_tags in enumerate(predicted_tags):
                for j, tag_id in enumerate(instance_tags):
                    class_probabilities[i, j, tag_id] = 1

            for metric in self.metrics.values():
                metric(class_probabilities, tags, mask.float())
            if self.calculate_span_f1:
                self._f1_metric(class_probabilities, tags, mask.float())
        if metadata is not None:
            output["words"] = [x["words"] for x in metadata]
        return output

    @overrides
    def decode(self, output_dict: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """
        Converts the tag ids to the actual tags.
        ``output_dict["tags"]`` is a list of lists of tag_ids,
        so we use an ugly nested list comprehension.
        """

        def decode_tags(tags):
            return [
                self.vocab.get_token_from_index(tag, namespace=self.label_namespace) for tag in tags
            ]

        output_dict["tags"] = [decode_tags(t) for t in output_dict["tags"]]

        return output_dict

    @overrides
    def get_metrics(self, reset: bool = False) -> Dict[str, float]:
        metrics_to_return = {
            metric_name: metric.get_metric(reset) for metric_name, metric in self.metrics.items()
        }

        if self.calculate_span_f1:
            f1_dict = self._f1_metric.get_metric(reset=reset)
            if self._verbose_metrics:
                metrics_to_return.update(f1_dict)
            else:
                metrics_to_return.update({x: y for x, y in f1_dict.items()})
        return metrics_to_return
