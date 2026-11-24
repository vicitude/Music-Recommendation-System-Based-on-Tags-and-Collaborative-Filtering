export type EvaluationMetric = {
  precision: number
  recall: number
  f1: number
  hit: number
  ndcg: number
  coverage: number
  diversity: number
  novelty: number
}

export const simulatedEvaluation = {
  "status": "SIMULATED_SELF_TEST",
  "source": "C1_FORMAL_V1_SEED42",
  "versions": {
    "profile": "formal-v1",
    "vocabulary": "formal53",
    "context": "eight-period-v1",
    "evaluation": "c2-six-route-v1"
  },
  "sha256": {
    "manifest.json": "d9c56d17de31a350d1397b72cdf0449db1934b59cd25949f880c34f67210ef9e",
    "data.json": "29f5d0609345acfc4192c19cf70efa2d5705e6178f8ff094e42394cbe39ee136"
  },
  "generator": {
    "seed": 42,
    "users": 200,
    "songs": 40,
    "interactions": 2927
  },
  "split": {
    "train": 2051,
    "validation": 294,
    "test": 582,
    "targetUsers": 200
  },
  "preference": [
    {
      "name": "电子",
      "value": 25.146198830409354,
      "color": "#d97855"
    },
    {
      "name": "R&B",
      "value": 21.637426900584796,
      "color": "#9c7bb5"
    },
    {
      "name": "夜晚",
      "value": 20.46783625730994,
      "color": "#6f9f9b"
    },
    {
      "name": "活力",
      "value": 16.95906432748538,
      "color": "#d2a85e"
    },
    {
      "name": "学习",
      "value": 15.789473684210526,
      "color": "#6f789f"
    }
  ],
  "routeWeights": [
    {
      "name": "标签内容",
      "value": 0.627665788455752,
      "color": "#d97855"
    },
    {
      "name": "用户协同",
      "value": 0.17574707135794482,
      "color": "#9c7bb5"
    },
    {
      "name": "歌曲协同",
      "value": 0.1965871401863037,
      "color": "#6f9f9b"
    }
  ],
  "methods": {
    "HOT": {
      "precision": 0.07300000000000001,
      "recall": 0.25958333333333333,
      "f1": 0.11395389626659987,
      "hit": 0.49,
      "ndcg": 0.15469843797785438,
      "coverage": 0.65,
      "diversity": 0.33921366843033507,
      "novelty": 0.672215
    },
    "CONTENT": {
      "precision": 0.21350000000000002,
      "recall": 0.7258333333333333,
      "f1": 0.3299476579134138,
      "hit": 0.915,
      "ndcg": 0.5461330316006575,
      "coverage": 1.0,
      "diversity": 0.4527894901394901,
      "novelty": 0.7130075
    },
    "USER_CF": {
      "precision": 0.1025,
      "recall": 0.34541666666666665,
      "f1": 0.15808837209302323,
      "hit": 0.725,
      "ndcg": 0.20771829588826013,
      "coverage": 1.0,
      "diversity": 0.6836025974025974,
      "novelty": 0.75685
    },
    "ITEM_CF": {
      "precision": 0.085,
      "recall": 0.295,
      "f1": 0.13197368421052633,
      "hit": 0.54,
      "ndcg": 0.1803017396796493,
      "coverage": 0.825,
      "diversity": 0.4080000801667468,
      "novelty": 0.6835249999999999
    },
    "FIXED": {
      "precision": 0.1805,
      "recall": 0.61375,
      "f1": 0.27895971041863393,
      "hit": 0.86,
      "ndcg": 0.42358777329257885,
      "coverage": 1.0,
      "diversity": 0.42119320586820586,
      "novelty": 0.6992875000000001
    },
    "ADAPTIVE": {
      "precision": 0.205,
      "recall": 0.7,
      "f1": 0.31712707182320443,
      "hit": 0.895,
      "ndcg": 0.5088629676746411,
      "coverage": 1.0,
      "diversity": 0.4391817821067821,
      "novelty": 0.7071025
    }
  },
  "contexts": [
    {
      "context": "凌晨",
      "hour": 2,
      "changed_users": 0,
      "users": 200,
      "mean_weights": {
        "content": 0.6171674079181579,
        "user_cf": 0.1914162960409214,
        "item_cf": 0.1914162960409214,
        "ncf": 0.0
      }
    },
    {
      "context": "清晨",
      "hour": 6,
      "changed_users": 0,
      "users": 200,
      "mean_weights": {
        "content": 0.6171674079181579,
        "user_cf": 0.1914162960409214,
        "item_cf": 0.1914162960409214,
        "ncf": 0.0
      }
    },
    {
      "context": "上午",
      "hour": 9,
      "changed_users": 0,
      "users": 200,
      "mean_weights": {
        "content": 0.6171674079181579,
        "user_cf": 0.1914162960409214,
        "item_cf": 0.1914162960409214,
        "ncf": 0.0
      }
    },
    {
      "context": "午间",
      "hour": 12,
      "changed_users": 0,
      "users": 200,
      "mean_weights": {
        "content": 0.6171674079181579,
        "user_cf": 0.1914162960409214,
        "item_cf": 0.1914162960409214,
        "ncf": 0.0
      }
    },
    {
      "context": "下午",
      "hour": 15,
      "changed_users": 0,
      "users": 200,
      "mean_weights": {
        "content": 0.6171674079181579,
        "user_cf": 0.1914162960409214,
        "item_cf": 0.1914162960409214,
        "ncf": 0.0
      }
    },
    {
      "context": "傍晚",
      "hour": 18,
      "changed_users": 0,
      "users": 200,
      "mean_weights": {
        "content": 0.6171674079181579,
        "user_cf": 0.1914162960409214,
        "item_cf": 0.1914162960409214,
        "ncf": 0.0
      }
    },
    {
      "context": "夜晚",
      "hour": 21,
      "changed_users": 31,
      "users": 200,
      "mean_weights": {
        "content": 0.6591609300685343,
        "user_cf": 0.12873939730901507,
        "item_cf": 0.21209967262245052,
        "ncf": 0.0
      }
    },
    {
      "context": "深夜",
      "hour": 23,
      "changed_users": 31,
      "users": 200,
      "mean_weights": {
        "content": 0.6591609300685343,
        "user_cf": 0.12873939730901507,
        "item_cf": 0.21209967262245052,
        "ncf": 0.0
      }
    }
  ],
  "limitations": [
    "Synthetic timestamps and preferences; not real user effectiveness",
    "Only completed plays used as implicit positive feedback",
    "Validation held out; no tuning",
    "Context comparison measures sensitivity, not context relevance"
  ]
}

export type SimulatedEvaluation = typeof simulatedEvaluation
