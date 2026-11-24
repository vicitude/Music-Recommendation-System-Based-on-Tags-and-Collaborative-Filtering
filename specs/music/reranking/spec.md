# SPEC-DIV-002：推荐重排接入与惊喜度评价

## 0 元数据
状态：已批准；v1.0.0；负责人项目用户/当前Agent；关联backend/music/diversity.py、recommendation.py、test_diversity.py；无数据库迁移、HTTP字段变更。取代specs/music/diversity单文件草案的公式与集成边界。Gherkin绑定unittest，无HTTP因此OpenAPI不适用。门禁：python -I -B -c内插入backend路径，运行music.test_diversity/test_recommendation/test_ncf/test_evaluation；全量使用config.test_settings SQLite内存。例：失败一项不算完成。

## 1 术语
|术语|英文|类型|定义|代码|数据库|示例|
|---|---|---|---|---|---|---|
|相异度|distance|值|1-Jaccard标签集合，两空为0|tag_distance|无|{1}/{2}=1|
|意外性|unexpectedness|值|与历史歌曲最大标签相似度的补值|discovery_metrics|无|与历史完全相同为0|
|惊喜度代理|serendipity|值|测试命中×意外性，非主观体验|discovery_metrics|无|命中且距离.5贡献.5|
|探索分|exploration|值|历史标签关联与低热度的乘积|serendipity_score|无|有关联且低热度才非零|

## 2 场景
```gherkin
Feature: 多样性重排
 Scenario: UT-DIV-008 推荐接入
  Given 同origin截止前反馈与完整有效歌曲标签
  When recommend默认调用
  Then 推荐使用重排且不突破原候选过滤
 Scenario: UT-DIV-009 公平对照
  Given 相同输入
  When enable_rerank=False
  Then 返回原融合排序且分数与开启重排的对应歌曲一致
 Scenario: UT-DIV-010 评价命中
  Given 训练历史与测试相关歌曲
  When 计算惊喜度
  Then 仅测试命中的意外歌曲计贡献且测试目标不参与重排
```
权限：只操作内存，不新增写入路径。空列表、全热门、缺标签正常处理。

## 3 接口
保留tag_distance(left_tags:tuple[int,...],right_tags:tuple[int,...])->float，serendipity_score(*,song_id:int,user_history_tags:set[int],song_tags:dict[int,tuple[int,...]],popularity:dict[int,int])->float，rerank_diverse(*,items:list[dict],song_tags:dict[int,tuple[int,...]],popularity:dict[int,int],user_history_tags:set[int],limit:int,diversity_weight:float=.25,serendipity_weight:float=.10)->list[dict]。
新增discovery_metrics(*,recommendations:dict[int,list[int]],targets:dict[int,set[int]],histories:dict[int,set[int]],song_tags:dict[int,tuple[int,...]],k:int=10)->dict[str,float|None]。
recommend原签名追加enable_rerank:bool=True；evaluate_methods原签名追加enable_rerank:bool=True并透传。HTTP不提供新开关。例：离线调用recommend(...,enable_rerank=False)。

## 4 数据模型/校验
ID为正int非bool；热度每值非负int非bool，标签每项正int；items为最多20个唯一歌曲字典，score为[0,1]有限数非bool。limit整数0..20；权重有限非负且和<=1；enable_rerank严格bool；k为正int。缺失标签为空，热度0。返回字段不扩展，深复制item保留嵌套证据、原score/source/explanation，仅rank变动。错误一律ValueError；未知指标歌曲按无标签，无训练历史的指标用户跳过。例：NaN权重拒绝。

## 5 算法/状态
探索分=(1-pop/max_pop)*Jaccard(history_tags,song_tags)，max_pop=0时novelty=1；两者无交集则0，不把随机不相关冷门曲当惊喜。多样性仍为已选平均距离（不是经典max-sim MMR，明确称MMR式平均距离重排）。utility=(1-d-s)*score+d*mean_distance+s*exploration。首曲固定原第一名，其余最高utility，平分按score降序再ID升序。权重全0严格保留输入顺序（含同分和任意输入顺序）。HOT和个性化分别重排后拼接，纯HOT全列表保持热门顺序，不让热门探索挤掉有个性化证据歌曲。
接入在recommend获得融合top20之后，不改fuse_candidates、不扩大候选池：先用原limit获得结果，再重排该列表，因此当前只能改变top20/所请求列表内部顺序，不能宣称从整曲库找回更多歌曲。song_tags来自songs的active_tags交集；history_tags来自positive_matrix目标用户正反馈对应songs的有效标签；popularity用同origin截止前matrix的不同正反馈用户数。没有完整历史标签时探索项0，多样性仍可执行。已有快照不自动刷新。
评价独立于旧catalog_metrics（旧novelty口径不改、不覆盖历史报告）：每用户去重topk，每歌曲unexpectedness=min(distance(song,历史歌))；缺候选/历史标签时0。仅历史非空且推荐非空用户纳入；unexpectedness为topk实际条数均值；serendipity为sum(测试命中*unexpectedness)/k，所有纳入用户等权平均；无用户两值None。例：k2历史{1},推荐[同标签2,异标签3]，targets{3}，得到.5/.5。
状态INPUT→VALIDATED→RERANKED，非法输入异常不产生输出，不写状态。

### Properties
P-DIV-01：∀输入，零权重输出为输入前limit且不修改输入（PT-DIV-001）。P-DIV-02：∀输出，ID集合为候选子集、唯一、连续rank、第一首不变（PT-DIV-002）。P-DIV-03：固定输入结果一致；首项固定、其余候选乱序不改变结果（PT-DIV-003）。P-DIV-04：∀指标0<=值<=1，非命中惊喜度0（UT-DIV-010）。生成器为seed0..9的20首有限分/标签样本，不引入新PBT依赖。

## 6 错误与日志
ValueError：字段/权重/开关非法，例bool limit。无新HTTP码，异常上游原样处理；算法无日志，无凭据与用户数据打印。

## 7 测试矩阵
UT-DIV-001距离手算，002探索相关性，003任意零权顺序，004手算重排，005全面校验，006深复制/缺标签/HOT，007集成数据映射，008开启重排效果，009开关对照/过滤/未来/异origin隔离，010指标手算/无命中/空历史；PT-DIV-001..003对应性质。全部自动化期限本阶段结束，归属test_diversity.py；现有推荐原始融合测试不变。例004原[1 .9,2 .89同标签,3 .88异标签]重排[1,3,2]。

## 8 非功能
标准库，无安装/迁移/真实库写入。最多20个候选，预计算两两距离与探索分后O(n²+k*n²)，有界20；不承诺全曲库质量提升。门禁测试退出0、git diff --check；Django内存全量回归。原API Schema测试应通过，无字段变化。例：k=0拒绝。

## 9 约束/日志
不更换标签、不生成472正式模拟数据、不读取密码、不提交。0.25/0.10是未调优初值，不是实验最优；仅证明机制与构造样例，不宣称实际提升。ECharts下一阶段安装须授权。旧specs/music/diversity为历史草案，仅保留不删除。Git未提交，日志不虚构，由后续Git记录生成。
