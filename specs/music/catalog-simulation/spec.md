# SPEC-SIM472-001：472 首离线模拟对照

## 0. 元数据

状态：已批准实施，v1.0.0。PO：项目用户；TL/QA：主会话。实现绑定 `backend/music/evaluation/catalog_simulation.py`、`backend/music/test_catalog_simulation.py`。无 HTTP、路由或迁移。下述 Gherkin 的本地执行绑定是 §7 的 unittest，无新框架；门禁为 §8 命令。示例：输出到不存在的 `local-ai/evaluations/sim472-seed42`。

## 1. 统一术语

| 术语 | 英文名 | 类型 | 定义 | 代码映射 | 数据库映射 | 示例 |
|---|---|---|---|---|---|---|
| 冻结曲库 | Catalog | 值对象 | 只读导出的 472 首可播放歌曲、所用启用标签 | `catalog` | 输入文件；实验不连库 | `catalog-472-v1` |
| 模拟行为 | SIMULATED | 枚举 | 合成事件与时间，不是真实用户行为 | `origin` | 无 | 用户 1 |
| 排序方法 | Method | 枚举 | 按表中顺序 `HOT, CONTENT, USER_CF, ITEM_CF, NCF, FIXED_4, ADAPTIVE_4, ADAPTIVE_4_RERANK, ADAPTIVE_NO_NCF` | `methods` | 无 | `FIXED_4` |
| 历史组 | Cohort | 枚举 | 按训练正反馈计数分为 `cold_start_0, light_1_9, regular_10_29, heavy_30_plus` | `groups` | 无 | 5 条属于轻度 |

## 2. 场景

```gherkin
Feature: Frozen offline experiment
  Scenario: Identical simulated inputs reproduce ranks
    Given a valid frozen catalog and seed 42
    When the offline command runs twice to two absent directories
    Then the generated files and rankings are byte-identical
  Scenario: No feedback leakage
    Given a user in cold_start_0 with four test positives
    When the model fits on training rows only
    Then NCF is unavailable for that user and neither held-out partition affects scoring
  Scenario: Protect previous output
    Given an existing output directory
    When the offline command is requested
    Then it fails without overwriting any file
  Scenario: Scope boundary
    Given a changed or malformed snapshot
    When generation is requested
    Then it stops with INVALID_CATALOG and does not access MySQL
```

## 3. 接口

从 `backend` 执行 `..\.venv\Scripts\python.exe -B -m music.evaluation.catalog_simulation --catalog PATH --output PATH --seed 42`。`--catalog` 与 `--output` 为必填路径；`--seed` 为 int，默认 42，范围 0..4294967295。成功退出 0；参数/输入错误退出 2。公共工厂：`generate(catalog: dict, seed: int) -> dict`；`compare(dataset: EvaluationDataset, split: TimeSplit) -> tuple[dict, dict]`，依序返回结果和排序。不存在 HTTP 契约（无端点，OpenAPI 不适用）。

## 4. 数据模型

输入 `catalog` 对象必需 `catalog_version`（固定 `catalog-472-v1`）、非空 `scope` 字符串、`songs`（472 条 `{song_id: int, tag_ids: list[int]}`）、`tags`（`{id: int, kind: str, name: str}` 列表；kind 是 `STYLE/MOOD/SCENE`）。ID 严格为正整数、实体 ID 不重复、每歌曲至少一条不同的有效标签引用，标签名去除前后空白后不变且长度 1..30。输入顺序不影响生成；先按 ID 排序。无数据库映射或 ORM 写入。

`data.json` 复用 `load_dataset` 的 songs/users/interactions 输入：用户 `{user_id, interest_tag_ids}`，事件 `{user_id, song_id, occurred_at, positive}` 全部必填。`manifest.json` 使用现有 v1 必填字段，另外必填 `catalog_sha256`、`data_sha256`、`seed`、`timestamp_origin`；固定 `source=SIM472_V1`, `origin=SIMULATED`, `timezone=UTC`, `timestamp_origin=SYNTHETIC`, `data_file=data.json`。`timestamps_are_real=true` 仅兼容旧读入器的真实时间格式门槛，时间本身是合成 UTC 顺序，不是真实采集；`license_evidence` 写“本机离线元数据与合成行为；不授权音频再分发”。

`report.json` 必填 `origin, catalog_sha256, data_sha256, ranking_sha256, seed, configuration, split, groups, methods`。`configuration` 必填 `k=10, shortlist=20, scene_enabled=false, tuned=false, ncf_factors=8, ncf_epochs=30, ncf_seed=42, ncf_learning_rate=0.01`。`split` 含 `train, validation, test` 计数及 ISO 字符串 `train_end, validation_end`。`groups` 以四个历史组为键，值为人数。每个 `methods` 值含 `overall`（指标字典）和 `groups`（同指标按组），以及 `signal_users`（至少一个候选非零路由分的用户数；HOT 为至少一个候选有训练流行度的用户数）。指标必填 `users, precision, recall, f1, hit, ndcg, coverage, diversity, novelty, unexpectedness, serendipity`；无目标或无合格历史时沿用对应工具返回空值。`rankings.json` 为方法→用户 ID 字符串→不超过 20 个歌曲 ID 的列表。`ncf-model.json` 采用现有 `music-ncf-mlp-v1`。

## 5. 规则与状态

`验证目录和输入 → 生成与载入 → 按时间切分 → 只用训练窗拟合并打分 → 写报告`。输出目录用独占 mkdir；JSON 采用 UTF-8、ensure_ascii=False、sort_keys=True、indent=2、结尾换行；SHA-256 对确切字节计算。失败保留已经产生的本地文件，不写成功结论、不重用目录。

生成器用 `random.Random(seed)`。200 人按 ID 1..200，四组各 50 人，训练正反馈配额依次 0/5/17/34；每人验证 2 条、测试 4 条，共 2800/400/800。每首按歌曲 ID 排序，依次从 RNG 抽 0..11 的潜类；每用户按 ID 抽一个偏好潜类与两个不同的曲库风格/情绪标签（无风格/情绪时使用全部标签，少于 2 个取所有）。冷启动前 25 人不公布显式兴趣，但仍有模拟偏好。每人从未选过的歌曲中按权 `1 + 4 * 潜类匹配 + 标签交集数量` 无放回抽样；每第 5 次抽样用均匀权重，计数从 1 跨三窗连续。所有行为标为正向。先按固定用户顺序产生三窗各自事件，再用同一 RNG 依次在窗内打乱；串接后时间从 `2026-01-01T00:00:00+00:00` 起逐条增加一分钟。用 `time_split` 检查实际切分为 2800/400/800。

指标只对候选内有测试正例的用户计算。候选 = 总曲库减训练已正反馈。复用 `_signals`、`positive_matrix`、词向量与推荐内容点积、User-CF、Item-CF；用含全部冻结曲目的同一份 `fit_ncf` 模型预测 NCF，拟合只执行一次；不使用场景，验证集不寻优。基线按单路分降序，零分项按训练流行度降序，再按 ID 升序；分数均为零时按热门兜底。固定融合只用候选最大分大于零的路由，单路除以其候选最大分后等权求和；正分并列按 ID 升序，零分按热门兜底。自适应调用现有 `fuse_candidates`；无 NCF 消融仅将 NCF 分数替换为空。两版重排共享自适应初排 Top20；重排使用原实现默认权重、该用户训练标签和同候选流行度。排序不读取验证或测试行为；只用测试行为确定命中。每组只使用该组推荐和目标计算排名指标；目录多样性与新颖性复用原口径（新颖性参照统计的用户集合），探索指标复用 `discovery_metrics`。示例：同一 Top20 输入，重排可改变 Top10 成员，但不能改变 Top20 成员集合。

### Properties

| ID | 回链与量化式 | 生成器 | 自动化 |
|---|---|---|---|
| P-SIM472-01 | §2、§5：对任意有效快照和种子，重复 generate 值相同；验证/测试正反馈不进入训练 | 472 首、多标签受控目录 | PT-SIM472-001 |
| P-SIM472-02 | §2、§5：对所有用户和方法，排序候选闭包，重排前后 Top20 集合同一；改动验证/测试不改变排序 | 同一训练窗，两份留出分区 | PT-SIM472-002 |

## 6. 错误与日志

| 错误码 | HTTP | 触发 | 日志 |
|---|---|---|---|
| `INVALID_CATALOG` | 不适用 | JSON 不可读或 §4 目录结构无效 | stderr，退出 2 |
| `OUTPUT_EXISTS` | 不适用 | 目标目录已出现，如旧实验 | stderr，退出 2 |
| `EVALUATION_FAILED` | 不适用 | 数据集/切分错误、写入失败或算法 ValueError | stderr，退出 2 |

成功只输出结果目录；不打印凭据，不连库。参数非法由 argparse 退出 2。

## 7. 覆盖矩阵

| 来源 | 需求 ID | 类型 | 用例 | 自动化状态 |
|---|---|---|---|---|
| §2、§5 | P-SIM472-01 | 性质 | PT-SIM472-001 | 已自动化：music.test_catalog_simulation，2026-11-18通过 |
| §2、§5 | P-SIM472-02 | 性质 | PT-SIM472-002 | 已自动化：music.test_catalog_simulation，2026-11-18通过 |
| §2、§6 | REQ-SIM472-03 | 单元 | UT-SIM472-003 | 已自动化：music.test_catalog_simulation，2026-11-18通过 |

## 8. 非功能及门禁

本地运行 `..\.venv\Scripts\python.exe -B -m unittest music.test_catalog_simulation music.test_evaluation`（cwd `backend`）要求失败数 0。无新依赖和 HTTP/DB 请求；验收以两次独立运行的 `manifest.json/data.json/report.json/rankings.json` 摘要一致、相同 Top20 成员，以及 NCF 制品加载成功为准。无额外 CI 服务。

## 9. 约束与版本

使用现有 Python/NumPy；模型拟合和浮点复现以同一环境为基准。自动标签只作为带噪输入，标签准确率、真人效果、音频重新分发权限均不是结论。示例：自适应 F1 低于内容时照实报告，不筛除不利结果。不安装依赖、不迁移、不提交、不改旧制品。Git 版本历史由 Git 提供；未提交，不虚构记录。
