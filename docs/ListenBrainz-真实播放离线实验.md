# ListenBrainz 真实播放离线实验：数据核验、运行手册与论文草稿

## 1. 当前证据（2026-11-20）

- **已实现**：独立导入与评估脚本。导入检查 SHA-256，流式读取编号 `.listens`，只在专用本地目录保存编号化数据、来源及参数清单；评价另建目录，只输出汇总报告。业务 MySQL、线上推荐和现有模拟实验均未变动。
- **已运行**：六项合成夹具专项测试通过，覆盖归档/校验和、时间切分与去重、用户标识不落盘、MSID/MBID 隔离、内容标签限制，以及官方字段格式的合成归档从导入到只输出汇总报告的全流程；既有规格自检与环境检查已通过。这些不是实测推荐结果。
- **已核验**：原获批的 `listenbrainz-sample-dump-20250610-094311.tar.zst` 是约 235 MiB 的样本，但不是逐用户播放日志。下载中止，保留原始校验文件和未完成文件；未完成文件未做完整校验、未进入训练。局部归档成员与[发布同期的官方样本导出实现](https://github.com/metabrainz/listenbrainz-server/blob/69246933c082436af41b6806383a9f49a9548512/listenbrainz/dumps/sample.py)一致：输出元数据、聚合流行度和辅助数据，不输出逐用户、逐时间的 listen 序列。聚合用户数也不能逆推出交互。
- **已初查（未校验前缀）**：2798 包的头部可见 `SCHEMA_SEQUENCE`、`START_TIMESTAMP`、`END_TIMESTAMP`、含 CC0 标记的 `COPYING`，以及 `listens/2026/11.listens`。首 1,000 行均有整数用户键、整数播放时间及字符串 MSID，未观察到逐条整数 `inserted_at` 或服务端 `recording_mbid` 映射；只检查字段存在性，没有输出任何原始行。前缀不能证明全包结构或字段覆盖。
- **已下载并校验**：2798 共 589,548,386 字节，SHA-256 `f05ea3e7bcdf49916f395573f66724aecb0555e1d6c9cd4bed500631ada66e4b` 与官方旁文件一致，2026-11-20 10:57:31 UTC 完成。全包成员列表有五项，其中一个 `.listens`。归档入库批次起止为 `2026-11-19T00:00:03.781257+00:00` 至 `2026-11-20T00:00:02.807158+00:00`，不是播放时间区间。
- **已定位首次导入失败**：SQLite 的 1 GiB 临时文件上限不足；默认值保留，当前运行显式使用 4 GiB 上限，启动前要求目标盘至少仍有 5 GiB 空闲。第二次导入越过读取阶段，但 500 用户／2,000 曲目的预设上限导致导出事件超过 20 万条，未生成评分或数据集。第三次独立运行改用 125 用户／750 曲目上限，仍保持同一全量时间划分、用户抽样顺序、曲目门槛和隐式反馈定义；该变更由资源限制触发，不依据评价结果。
- **已运行真实实验**：MSID 实验集的四个基线均完成，报告位于 `local-ai/evaluations/listenbrainz-v1/2798-msid-u125-i750-report/report.json`。125 个用户中 74 个有测试目标、测试目标对 1,153 个；训练用户—录音对 12,142 个、训练密度 0.1295；另有 51 个用户没有合格测试目标，按协议不进入总体指标。
- **实测总体 Top-10**：HOT：Precision 0.0649、Recall 0.0348、F1 0.0453、Hit 0.3784、NDCG 0.0780、Coverage 0.0907；USER_CF：与 HOT 数值相同（Precision 0.0649、Recall 0.0348、F1 0.0453、Hit 0.3784、NDCG 0.0780、Coverage 0.0907）；ITEM_CF：0.0595、0.0386、0.0468、0.3243、0.0745、0.3520；NCF：0.0716、0.0393、0.0508、0.4054、0.0854、0.0920。Novelty bits 依次为 HOT/USER_CF 8.7518、ITEM_CF 9.3577、NCF 8.7602；Diversity 因 MSID 数据没有独立标签而不可计算。NCF 的训练 BCE 从 0.6939 降到 0.5623。以上是该单个增量批次、单一抽样口径的实测值，不是总体 ListenBrainz 结论，也不宣称普遍提升。
- **已审计限制**：MSID 不能与 MusicBrainz 标签安全连接，因此 CONTENT、固定/自适应混合和标签重排序未运行；报告明确标记 `NOT_RUN_INSUFFICIENT_INDEPENDENT_TAGS`。Item cold-start 也未测量，报告标记 `TRAINING_CATALOG_ONLY`。
- **来源许可不替代对隐私的保护。**

## 2. 来源、字段和候选数据

[官方 dump 文档](https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html)区分逐行 JSON 的 `.tar.zst` 和 Spark Parquet 的 `.tar`。全量通常每月两次更新，增量按日发布，按记录入库时间确定批次，而不是按照实际播放时间截取。调研时官方 [2026-11-15 全量目录](https://ftp.musicbrainz.org/pub/musicbrainz/listenbrainz/fullexport/listenbrainz-dump-2789-20261115-000003-full/)显示 JSON 听歌归档约 246 GiB、Spark 约 245 GiB，不适用于本轮本机实验。已匿名访问公开文件索引和 HTTP 文件头；[官方访问说明](https://metabrainz.org/datasets/signup)及[许可页](https://metabrainz.org/datasets/postgres-dumps)适用于本实验的免费公开数据，ListenBrainz 数据许可为 CC0 1.0，不赋予音频版权。[MusicBrainz 主数据和补充数据分别适用不同许可](https://musicbrainz.org/doc/About/Data_License)，如采用补充标签，需核对 CC BY-NC-SA 3.0 的具体适用范围、署名、非商业与相同方式共享条件。

[官方归档导出器](https://github.com/metabrainz/listenbrainz-server/blob/master/listenbrainz/listenstore/dump_listenstore.py)调用 [Listen.to_json](https://github.com/metabrainz/listenbrainz-server/blob/master/listenbrainz/listen.py)，写出 `user_id`、`user_name`、`timestamp`、`track_metadata` 和 `recording_msid`；[API JSON 文档](https://listenbrainz.readthedocs.io/en/latest/users/json.html)则使用 `listened_at`，可有 `inserted_at` 和 `track_metadata.mbid_mapping`。这两种表示不能混用假设：JSON 归档不保证带已解析 MBID 或入库时间。仅使用归档时，`timestamp` 是 UTC 的听歌事件时间，不能证明播放完成、播放时长、跳过、评分、收藏、心情、场景或用户所在地。

下一候选：官方[增量目录 2798](https://ftp.musicbrainz.org/pub/musicbrainz/listenbrainz/incremental/listenbrainz-dump-2798-20261120-000002-incremental/)的 JSON 归档 `listenbrainz-listens-dump-2798-20261120-000002-incremental.tar.zst`，HTTP HEAD 为 **589,548,386 字节（约 562 MiB）**，另有 64 字节 SHA-256 旁文件。计划保存到 `local-ai/real-data/listenbrainz/raw/`，预留至少 2 GiB，压缩包不整体解压；程序对压缩包、流式读取和 SQLite 临时文件分别设上限。**用户已授权下载该归档与官方 SHA-256 旁文件；只有完整归档通过校验后才会导入。** 该增量仅覆盖一个入库批次，可能包含回填旧播放，也可能没有足够的重叠歌曲、用户或可评测目标。它是先导实验候选，不是有代表性的长期用户样本。

## 3. 本地运行手册

脚本位于 [导入器](../backend/music/evaluation/listenbrainz_import.py)、[评价器](../backend/music/evaluation/listenbrainz_eval.py)，验证用 [专项测试](../backend/music/evaluation/test_listenbrainz_offline.py)。在 `backend` 工作目录用项目虚拟环境运行：

```powershell
& '..\.venv\Scripts\python.exe' -B -m unittest -v music.evaluation.test_listenbrainz_offline
& '..\.venv\Scripts\python.exe' -B -m music.evaluation.listenbrainz_import --help
& '..\.venv\Scripts\python.exe' -B -m music.evaluation.listenbrainz_eval --help
```

批准并核验下载后，导入传入 `--archive`、`--checksum`、`--source-url`、`--downloaded-at`、`--snapshot-at`、`--secret-path` 和一个尚不存在、父目录已存在的 `--output`。使用原始归档的 MSID 实验时显式指定 `--identity msid`；本地密钥只留专用私有目录，复跑复用同一密钥。评价传入 `--manifest` 和新的 `--output`，放在 `local-ai/evaluations/listenbrainz-v1/` 下。未经另行审核，不要给评价器传标签文件，更不要共享原始归档、密钥或行级实验文件。正式结果只发布汇总。

## 4. 论文草稿：数据集与实验方法

本研究设置两个互相独立的离线实验。模拟实验使用自行构造的用户及业务行为，用于验证带标签的混合推荐、场景权重及重排序机制。真实播放实验采用 MetaBrainz 提供的 ListenBrainz 公共日志，以用户提交的听歌事件作为隐式正反馈，用于检验热门推荐、用户协同过滤、物品协同过滤与神经协同过滤在外部日志上的表现。两组实验的曲库、用户来源、行为定义和数据稀疏程度不同，分别报告指标，不用它们之间的分差推断算法提升。

数据预处理首先用官方 SHA-256 校验输入，删除无效时间和无有效曲目标识的行，并对同用户、同曲目和同秒事件去重。用户在实验文件中仅保留本地编号；课程项目的 User、Song 和 Behavior 分别由离线用户编号、离线录音编号及 `LISTEN` 事件表示，不写入业务数据库。若输入提供服务端解析的 MusicBrainz recording MBID，则在 MBID 模式使用该标识；仅有 MessyBrainz MSID 的归档在独立 MSID 模式使用，不假定其与 MusicBrainz 录音一一对应，也不与 MusicBrainz 标签连接。每个训练用户—曲目对权重为 1；跨秒重复播放用于计数诊断，不提高权重，不使用时间衰减。未观察到的交互不是负面偏好；NCF 的未观察配对采样仅是训练策略。

按 UTC 播放事件时间全局划分约 70% 训练、10% 验证、20% 测试；边界的同秒事件进入后一段。训练已知入库时间且在截点后才到达的事件被排除；若归档缺少入库时间，实验仅为基于事件时间的回顾性评估。训练区间用于抽取用户并构建曲库：最多 500 个用户、2,000 个录音标识，曲目至少由 3 名抽样训练用户听过。允许独立纳入少量没有可见训练历史的目标用户，但他们不参与模型拟合。对所有算法固定训练曲库和切分，排除用户训练时已见曲目，以测试窗口中剩余的去重首次目标为相关项；额外报告候选集外新目标和无合格目标用户数。验证段保留用于独立核验，本协议不据验证或测试指标调参。

结果采用 Top-10 评价，以 NDCG@10（对排名靠前的命中给更大权重）及 Recall@10（合格目标中被命中的比例）为主，同时报告 Precision、F1、Hit（至少一次命中）、Coverage（曾被推荐的训练曲库占比）和 Novelty（按平滑后的训练流行度计算信息量）。Diversity 使用有标签曲目对的 Jaccard 距离，并报告可计算对的比例；没有合规、可靠的截点前标签时记为不可计算，不填 0。用户按训练曲库中可用的历史曲目数分为 0、1–9、10–29、30+ 组；不足 5 名可评用户的分组不披露指标。0 只表示在本样本的训练曲库中无可用历史，不代表新注册用户。模型无信号时以训练期热门度兜底，另报无信号比例及 User-CF 支持曲目并列情况。冷启动仅考察用户分组；训练曲库限定意味着本协议不能评价真正的新曲目冷启动。

首轮实测结果见第 1 节。仅有 MSID 的实验不报告 CONTENT、融合或标签重排序结果；如后续拿到授权且冻结于训练截点前的标签，另行报告其匹配覆盖并运行标签相关方法。单批次提交偏差、回填、标识碎片、训练热门曲筛选、缺失入库时间、UTC 无法代替用户当地时区，均限制外推。

## 5. 固定曲库扩样对照（2026-11-21，已运行）

同一份本地 2798 归档、同一抽样密钥，将用户数由 125 扩到 200，沿用首轮的 750 个录音标识，以及 `2025-04-07T18:00:48+00:00` 和 `2026-02-20T21:01:09+00:00` 两条时间分界。已核对曲库逐项一致，首轮用户在该曲库内的播放事件在三段中均保留。四种方法使用相同的前 10 首评价规则和预设参数，在扩大后的训练集重新训练或计算分数。未根据测试成绩调参。

| 样本 | 用户总数 | 有合格目标、计入成绩的人数 | 曲库内测试目标对 | 曲库外新目标对 | 导出播放事件 |
|---|---:|---:|---:|---:|---:|
| 首轮 | 125 | 74 | 1,153 | 265,721 | 180,847 |
| 扩样 | 200 | 105 | 1,411 | 345,417 | 243,668 |

扩样训练／验证／测试分别导出 204,846／22,378／16,444 条事件，训练唯一用户—录音对 16,962，矩阵密度 11.31%。95 人没有合格测试目标，不计入指标。105 名计分用户，按训练中听过 0、1–9、10–29、至少 30 个候选录音分组，依次为 12、7、10、76 人；0 不表示新注册。

| 推荐方法 | 推荐命中比例 | 找回合格目标的比例 | 综合得分 | 至少命中一首人数 | 靠前排序得分 | 曲库覆盖 | 新颖度（比特） |
|---|---:|---:|---:|---:|---:|---:|---:|
| 热门推荐 | 5.81% | 3.80% | 0.0460 | 33/105（31.43%） | 0.0666 | 11.07% | 8.7293 |
| 相似用户推荐 | 5.81% | 3.80% | 0.0460 | 33/105（31.43%） | 0.0666 | 11.07% | 8.7293 |
| 相似歌曲推荐 | 6.76% | 3.66% | 0.0475 | 36/105（34.29%） | 0.0634 | 35.60% | 9.2153 |
| 神经网络推荐 | 6.00% | 4.20% | 0.0494 | 36/105（34.29%） | 0.0710 | 11.07% | 8.7368 |

**论文结果表述建议：** 在固定录音候选集和时间切分的扩样对照中，神经网络方法两轮均取得最高的靠前排序得分（0.0854、0.0710），但扩样后相似歌曲方法的推荐命中比例和曲库覆盖更高，两种方法至少命中一首的人数相同。相似用户方法与热门方法的汇总分数一致；扩样有 90 人的候选正分全部并列、15 人无正分，不能说所有用户都退回热门推荐。两轮用户有重叠，扩样同时改变了训练和计分人数；分数波动不能解释为扩样带来的性能增益或损失，也未检验显著性。两轮均来自同一提交批次，且不评价曲库外曲目、歌曲标签或线上效果。

导入的事件上限默认仍为 20 万，扩样显式使用 50 万上限，实际只导出 243,668 条，没有截断；使用 4 GiB 有界临时 SQLite，不接触业务库。复跑可用 `--fixed-catalog-manifest <首轮 manifest.json> --max-users 200 --max-items 750 --max-events 500000 --scratch-gib 4`，另用全新的输入、报告路径。六项合成夹具专项测试、现有规格和环境检查均通过。扩样证据：[来源与参数清单](../local-ai/evaluations/listenbrainz-v1/2798-msid-u200-i750-fixed-input/manifest.json)、[四种算法汇总报告](../local-ai/evaluations/listenbrainz-v1/2798-msid-u200-i750-fixed-report/report.json)。

## 6. 答辩口述稿

我们把模拟数据和真实播放实验分开。真实部分只把 ListenBrainz 记录当成听过，不推断评分、收藏或跳过；先按 UTC 时间划分，再用同一个训练曲库比较热门、User-CF、Item-CF 和 NCF。2798 增量归档校验通过，有约 1,553 万条有效播放记录；从中抽出 125 人做首轮，再用同一批 750 个录音、同样时间分界扩到 200 人，最终有 105 人可计分。扩样后，神经网络方法把后来听过的歌排得更靠前，相似歌曲方法命中比例更高、推荐覆盖更广，两种方法都让 36 人至少命中一首。两轮都来自同一批真实日志，不代表所有用户或线上效果。由于没有可安全连接的标签，内容和标签混合方法没有运行。
