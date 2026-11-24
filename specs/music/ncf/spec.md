# SPEC-NCF-001：神经协同过滤训练与预测

## 0 文档头与元数据
- 状态：已批准（用户同意先实现真正NCF）；版本v1.0.0；PO为项目用户，实施/测试为当前Agent。
- 关联：backend/music/ncf.py、backend/music/recommendation.py、backend/music/test_ncf.py、backend/music/test_recommendation.py。API路由和数据库迁移：无新增。
- 本规范Gherkin由同名unittest场景绑定执行；无HTTP端点，OpenAPI不适用，不引入生成器或新框架。状态机为下文确定性转换。
- 门禁：根目录执行 `.\.venv\Scripts\python.exe -I -B -c "import sys,unittest;sys.path.insert(0,'backend');r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(['music.test_ncf','music.test_recommendation']));sys.exit(not r.wasSuccessful())"`，退出0。实施后补Django内存全量回归。例：TC-NCF-001必须通过，不以名称包含NCF证明网络实现。

## 1 术语
|术语|英文名|类型|定义|代码映射|数据库映射|示例|
|---|---|---|---|---|---|---|
|反馈矩阵|matrix|值对象|正数为正反馈，0不作为正样本；仅上游cutoff与origin过滤后传入|dict[int,dict[int,float]]|无写入|{1:{10:3.0}}|
|神经协同模型|NCFModel|值对象|用户/歌曲embedding拼接，经两层tanh和sigmoid输出|NCFModel|无|8维embedding，16/8隐藏层|
|模型参数|parameters|值对象|eu,ei,w1,b1,w2,b2,wo,bo八个数组|dict[str,np.ndarray]|JSON制品|w1形状(16,16)|
|训练标识|fingerprint|值对象|训练矩阵、曲库、参数规范JSON的SHA256|str|JSON制品|64位十六进制|

## 2 可执行场景
```gherkin
Feature: 神经协同训练
 Scenario: TC-NCF-001 学到反馈
  Given 固定种子与分组正反馈矩阵
  When 训练两层神经网络
  Then BCE最终值低于初始值且embedding和隐藏参数均改变
 Scenario: TC-NCF-002 冷启动与候选边界
  Given 未知用户或空历史用户
  When 预测
  Then 返回空映射且不产生伪个性化分数
 Scenario: TC-NCF-003 制品往返
  Given 已训练模型
  When 保存为JSON并重新加载
  Then 同一用户同一候选的概率逐值一致
```
权限边界：无HTTP、无数据库、只写调用方显式选择的新文件；已有路径拒绝覆盖。坏制品拒绝而非执行反序列化代码。

## 3 接口契约
纯Python接口，无HTTP/状态码变更，不新建OpenAPI。
- `fit_ncf(*, matrix: dict[int, dict[int, float]], item_ids: tuple[int, ...], factors: int = 8, epochs: int = 30, seed: int = 42, learning_rate: float = 0.01) -> NCFModel`
- `predict_ncf(model: NCFModel, *, user_id: int, candidate_ids: tuple[int, ...]) -> dict[int, float]`
- `save_ncf(model: NCFModel, path: Path) -> None`
- `load_ncf(path: Path) -> NCFModel`
- `compute_ncf(*, user_id: int, matrix: dict[int, dict[int, float]], candidate_ids: tuple[int, ...], factors: int = 8, epochs: int = 30) -> dict[int, float]`兼容原调用名，替换旧MF实现。
例：fit_ncf(matrix={1:{1:1}},item_ids=(1,2))；predict_ncf返回已知候选概率(0,1)，不按候选集合min/max重缩放。
内部签名：`validate_inputs(matrix, item_ids, factors, epochs, seed, learning_rate) -> tuple`；`forward(parameters, user_indices, item_indices) -> tuple`；`loss_gradients(parameters, user_indices, item_indices, labels) -> tuple`；`_cached_model(rows: tuple, items: tuple, factors: int, epochs: int) -> NCFModel`，LRU最多8份。

## 4 数据模型与校验
NCFModel字段：user_ids tuple[int,...]、item_ids tuple[int,...]、positive_user_ids tuple[int,...]、factors int、epochs int、seed int、learning_rate float、fingerprint str、losses tuple[float,...]、parameters dict[str,np.ndarray]；均必填无None。模型训练后数组只读。
JSON顶层严格字段：format='music-ncf-mlp-v1'及以上十字段（tuple写成数组，parameters写数值嵌套数组）；拒绝额外字段。losses长度epochs+1，每个值有限且非负。fingerprint必须64位小写hex。正用户为user_ids子集。全部ID为正整数，不接受bool；ID列表唯一递增。factors 2..32、epochs 1..200、seed 0..2147483647整数非bool；learning_rate有限数值0<rate<=1非bool；matrix为字典，每行字典，值有限非负数且非bool。曲库为输入item_ids与所有正反馈歌曲ID并集。示例：输入item_ids=(2,)，matrix={1:{1:1}}仍训练歌曲1和2。
参数形状：eu(U,f)、ei(I,f)、w1(2f,16)、b1(16)、w2(16,8)、b2(8)、wo(8,1)、bo(1)。有限float64。模型加载上限16MiB，先检查字节数，再解析，形状/字段/格式全部验证。无pickle。

## 5 业务规则与状态机
1. 规范化排序用户、歌曲、矩阵；训练保留已收藏正例，不因推荐候选过滤丢弃。正样本label=1不按原评分重复；每用户从非正样本曲库采样min(4*正例数,可用负例数)无放回负例label=0。零正例用户不参与训练。
2. np.random.default_rng(seed)；embedding N(0,.1)，w1/w2/wo正态标准差sqrt(2/(fan_in+fan_out))，bias0。采样后全批训练，不shuffle。sigmoid使用截断logit[-30,30]；损失mean(logaddexp(0,logit)-label*logit)，隐层tanh；反向传播更新所有8参数。
3. Adam beta1=.9 beta2=.999 epsilon=1e-8，逐epoch一步，bias correction；不加L2/dropout，不用验证集/测试集训练。记录初始及每步后BCE。空样本损失为0，参数保持初始化。
4. predict只返回请求中模型已知歌曲；未知用户/无正历史返回{}，未知歌曲省略。概率直接输出，不按候选集归一化；单候选也有效。
5. compute校验输入后，空候选/未知或零历史用户返回{}；缓存key为规范化完整矩阵、曲库并集、factors、epochs；相同key训练一次跨用户复用；曲库变更或矩阵变更必须重训，最多8份进程内缓存。不自动读取或写制品，不使用不明cutoff模型。预测分数继续交现有四路融合；无模型信号由既有权重重分配处理。例：新用户ncf权重0。
6. save使用UTF8 JSON allow_nan=False及文件模式x，不覆盖。load不自动采用进线上引擎。
状态机：INPUT --校验通过--> TRAINING --epochs结束--> FITTED --save新路径--> SAVED --load验证--> FITTED；非法输入/制品抛ValueError，已存在路径抛FileExistsError，IO异常原样传播。不吞内部训练错误，不假冒可用模型。

### Properties
|性质|回链|量化式|生成器|测试|
|---|---|---|---|---|
|P-NCF-01|规则1/4|∀候选C,predict.keys ⊆ C；未知用户结果为空|固定seed的5种矩阵和候选子集|PT-NCF-001|
|P-NCF-02|规则2/3|∀相同规范输入，参数/概率一致；输入矩阵不变|乱序同值矩阵|PT-NCF-002|
|P-NCF-03|规则6|∀有效模型，load(save(m))预测=m预测|临时目录新路径|TC-NCF-003|

## 6 错误与日志
不新增API错误码。ValueError表示输入或制品不符合§4（例bool ID、NaN权重）；FileExistsError表示保存路径已存在；OSError表示文件IO失败。测试直接断言异常类型，不绑定文字。纯算法不打印用户数据/凭据、不接数据库、不修改快照；调用方可记录fingerprint及losses，不记录敏感信息。

## 7 需求与测试矩阵
TC-NCF-001训练降损/参数更新；TC-NCF-002冷启动；TC-NCF-003往返/拒绝覆盖；TC-NCF-004制品损坏；TC-NCF-005输入校验；TC-NCF-006有限差分验证全参数梯度（epsilon1e-5, atol1e-6）；TC-NCF-007缓存复用及失效；PT-NCF-001候选闭包/单候选/未知歌曲；PT-NCF-002确定性/输入不变。全部在backend/music/test_ncf.py以test_tc_ncf_001至007、test_pt_ncf_001/002实现；实施前未自动化，期限为本阶段结束前。现有test_ncf_excluded_history_still_trains_same_model改断言候选预测原概率不变，不再断言minmax归一化。test_simulated_neighbors_do_not_affect_real_collaborative_scores比较加模拟邻居前后结果完全一致，不再要求HOT：真实用户自己的正反馈仍能训练NCF，单候选预测不归零。test_daily.test_adapter_ignores_other_origins_future_feedback_and_inactive_neighbors不再把所有协同都视为不可用：本人正反馈与同origin历史可训练NCF，断言alpha_effective等于alpha_target，User-CF/Item-CF为0；现有未来/停用过滤断言保留。ID上限2**63-1；文件空参数数组只允许期望形状含0维的eu/ei，非空参数严格形状，拒绝字符串与bool数值。

## 8 非功能与门禁
无新增安装、迁移、业务库写入；用纯unittest验证。实现仅依赖标准库与requirements.in已有numpy。训练样本最多每个正例5行，cache maxsize8，模型文件16MiB上限；测试验证样本和缓存行为。CPU耗时记录但不承诺生产规模延迟，正式472曲库基准与质量实验不属于此阶段。加载不执行文件内容；有限差分覆盖全部八种参数。门禁以§0测试退出码及 `git diff --check -- backend/music/recommendation.py backend/music/test_recommendation.py` 为准。例：失败1项不称完成。

## 9 假设、约束、变更日志
输入为上游已过滤的同origin、cutoff前隐式正反馈，不引入SKIP负反馈或评分预测；采样负例仅未观测，不声称真实不喜欢。实现为NCF的MLP分支，不宣称完整NeuMF预训练或推荐效果提升。模型单独训练/预测/制品接口本阶段交付；标签人工复核、新模拟数据、多样性和ECharts另阶段。单会话，不提交、不改依赖或真实库。Git尚未提交，不虚构tag/commit；变更日志仅由将来Git历史生成，当前为空。
