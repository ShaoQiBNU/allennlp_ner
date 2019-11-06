allennlp NER应用实例
===================

# 一. 简介

基于allennlp框架在 CONLL 2003 数据集上采用BiLSTM+feedforward+CRF模型结构实现NER识别

# 二. 代码结构

## (一) configs

> configs文件夹下是配置文件，json格式，主要包含 **dataset_reader** , ** ..._data_path**, **model**, **iterator**, **trainer**。

### 1. dataset_reader

> dataset_reader是数据读取预处理部分，主要有 tokens 和 token_characters，tokens表示word level的处理，lowercase_tokens 表示word进行小写处理，token_characters表示character-level的处理

```json
"dataset_reader": {
    "type": "conll2003",
    "token_indexers": {
      "tokens": {
        "type": "single_id",
        "lowercase_tokens": true
      },
      "token_characters": {
        "type": "characters"
      }
    }
  }
```

### 2. data_path

> data_path是数据存储路径，

```json
"train_data_path": "data\\train.txt",
"test_data_path": "data\\test.txt",
```

### 3. model

> model是模型结构
text_field_embedder 表示数据预处理 —— word-level采用glove embedding，character-level采用multi-layer CNN 随机初始化embedding
encoder 表示模型结构BiLSTM，feedforward 表示全连接层，可有可无

```json
  "model": {
    "type": "BiLSTM_CRF",
    "text_field_embedder": {
      "token_embedders": {
        "tokens": {
          "type": "embedding",
          "pretrained_file": "glove\\glove.6B.300d.txt",
          "embedding_dim": 300,
          "trainable": true
        },
        "token_characters": {
            "type": "character_encoding",
            "embedding": {
            "embedding_dim": 16
            },
            "encoder": {
            "type": "cnn",
            "embedding_dim": 16,
            "num_filters": 128,
            "ngram_filter_sizes": [1,2,3,4,5,6,7],
            "conv_layer_activation": "relu"
            }
        }
      }
    },
    "encoder": {
      "type": "lstm",
      "input_size": 1196,
      "hidden_size": 200,
      "num_layers": 2,
      "dropout": 0.5,
      "bidirectional": true
    },
    "feedforward": {
      "input_dim": 400,
      "num_layers": 2,
      "hidden_dims": [250,100],
      "activations": ["relu", "relu"]
    },
    "dropout": 0.2,
    "calculate_span_f1": true,
    "label_encoding": "BIO"
  }
```

### 4. iterator

> iterator是产生数据流的相关设置，sorting_keys是排序key，可以让数据按照长度排序，这样每个batch下的数据按照最大输入长度填充批量，使计算（填充）更高效。
```json
  "iterator": {
    "type": "bucket",
    "sorting_keys": [["tokens", "num_tokens"]],
    "batch_size": 64
  }
```

### 5. trainer

> trainer是训练器相关的参数，epochs，optimizer等等

```json
  "trainer": {
    "num_epochs": 10,
    "patience": 10,
    "cuda_device": -1,
    "grad_clipping": 5.0,
    "optimizer": {
      "type": "adagrad"
    }
  }
```

## (二) dataset_readers

> dataset_readers下是数据读取文件，主要参考allennlp官方代码：https://github.com/allenai/allennlp/blob/master/allennlp/data/dataset_readers/conll2003.py

## (三) models

> models下是模型文件，主要参考allennlp官方CRF代码：https://github.com/allenai/allennlp/blob/master/allennlp/models/crf_tagger.py

# 三. 使用方法

```shell
# 训练
allennlp train configs/conll2003.json -s result/ --include-package models

# 评价
allennlp evaluate result/model.tar.gz data/test.txt --include-package models
```
