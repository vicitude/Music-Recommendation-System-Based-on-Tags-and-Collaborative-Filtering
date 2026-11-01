# SPEC-MUSIC-001：音乐推荐系统实现规格

## 第 0 部分：文档头与元数据

- 状态：开发中。版本：v0.1.0。负责人：PO / TL / QA 均为项目所有者，Agent 辅助实施。
- 目标：将已确认的业务范围与三项创新转为实现契约；本文不是功能完成证明。
- 编号：SPEC-MUSIC-001。文档日期：2026-10-29。当前未初始化 Git，无关联 Tag，不伪造提交记录。
- 关联代码路径：backend/music/、backend/config/urls.py、backend/music/migrations/0001_initial.py、backend/music/services.py、backend/music/tests.py、backend/music/recommendation.py、backend/music/daily.py、backend/music/media.py、backend/music/forms.py、backend/music/admin.py、backend/music/behavior.py、backend/music/test_recommendation.py、backend/music/test_daily.py、backend/music/test_behavior.py、backend/music/test_media.py、frontend/src/。24个API与管理/行为/推荐后端已实现。
- 制品：[API 契约](openapi.yaml)、[实体定义](entities.schema.json)、[状态机](states.yaml)、[验收场景](features/music.feature)、[实现任务](tasks.md)、[验收清单](checklist.md)、[落地自检](self-check.md)、[环境核验](environment.md)、[实施边界补充](implementation-boundaries.md)。
- 规范性补充：[迁移设计](migration-design.md)、[迁移映射](migration-plan.json)、[服务入口](service-contracts.md)、[API绑定](api-bindings.json)、[扩展性质](properties.md)、[文档门禁](verification.md)。
- 安装与锁定状态：[安装记录](installation.md)。既定范围已进入实施，最新结果见[跨模块回归](workflow-results.md)与[前端实施](frontend-results.md)，历史基础API见[实施验证](implementation-results.md)；数据库和素材授权边界保持不变。
- 可执行性：OpenAPI使用3.1.0，JSON编码为YAML1.2子集；场景已可解析但无步骤绑定，不能执行业务；状态机可被实现读取，尚无业务加载器。文档门禁可以独立运行，不宣称业务测试已通过。
- 实施门槛：文档门禁verify_spec.py --self-test --check-environment必须通过后，允许进入业务实现；completion-contract.md、migration-design.md、service-contracts.md和frontend-contract.json是实现契约。业务TC/PT、数据库迁移、前端typecheck/build和CI接入必须在对应阶段执行，未执行不得标记完成。
- 优先级：本文获批后作为实现需求的唯一事实源；原设计方案保留研究背景，不重复承担实现契约。权限、音频许可与数据真实性约束不因技术调整而放宽。
- 示例：本轮仅基础API通过内存测试，不能在报告中写成“完整系统已验收”或“MySQL已验证”。

## 第 1 部分：术语表与统一语言

| 术语 | 英文名 | 类型 | 定义 | 代码映射 | 数据库映射 | 示例 |
|---|---|---|---|---|---|---|
| 用户 | User | 聚合根 | Django 用户扩展，staff 为管理角色 | music.User | music_user | id=1 |
| 歌曲 | Song | 聚合根 | 可检索的曲库条目 | music.Song | music_song | title=测试曲 |
| 标签 | Tag | 值对象 | 人工维护的内容属性 | music.Tag | music_tag | name=治愈 |
| 标签类型 | TagKind | 枚举 | STYLE、MOOD、SCENE，顺序固定 | TagKind | music_tag.kind | MOOD |
| 歌曲标签 | SongTag | 值对象 | 歌曲和标签关联 | music.SongTag | music_song_tag | weight=1 |
| 用户兴趣 | UserTag | 值对象 | 当前显式偏好集合 | music.UserTag | music_user_tag | user_id=1 |
| 收藏 | Favorite | 值对象 | 当前有效收藏关系 | music.Favorite | music_favorite | song_id=2 |
| 歌单 | Playlist | 聚合根 | 只对所有者可见的歌单 | music.Playlist | music_playlist | name=睡前 |
| 歌单歌曲 | PlaylistSong | 值对象 | 不重复歌曲集合，按加入时间排序 | music.PlaylistSong | music_playlist_song | song_id=2 |
| 行为 | Behavior | 聚合根 | 服务器接受的播放事件 | music.Behavior | music_behavior | event_id=UUID |
| 行为类型 | BehaviorKind | 枚举 | PLAY、COMPLETE、SKIP，顺序固定 | BehaviorKind | music_behavior.kind | COMPLETE |
| 来源 | DataOrigin | 枚举 | REAL、SIMULATED，顺序固定 | DataOrigin | User / Behavior.origin | REAL |
| 推荐来源 | RecommendationSource | 枚举 | CONTENT、CF、HYBRID、HOT，顺序固定 | RecommendationSource | snapshot.items[].source | HYBRID |
| 每日快照 | RecommendationSnapshot | 聚合根 | 用户当天的有序推荐结果与证据 | music.RecommendationSnapshot | music_recommendation_snapshot | revision=1 |
| 推荐项 | RecommendationItem | 值对象 | 含歌曲、分项得分及解释 | RecommendationItem | snapshot.items JSON | rank=1 |
| 会话 | ListeningSession | 值对象 | 一首歌的一次播放，不等于登录会话 | UUID | behavior.listening_session_id | UUID v4 |

实体全部业务字段见第 4 部分与 entities.schema.json。Django 内置权限与会话表由框架维护，不自建密码、令牌表。所有枚举在本文和 Schema 保持一致。

## 第 2 部分：用户故事与验收场景

| 需求 ID | 用户故事 | 验收场景 ID | API 或界面 |
|---|---|---|---|
| REQ-01 | 注册登录并只访问自己的数据 | TC-M-001、TC-M-002 | /auth/*、/playlists/{id}/ |
| REQ-02 | 选择兴趣或跳过引导 | TC-M-003 | PUT /me/interests/ |
| REQ-03 | 搜索、筛选并播放合法曲库 | TC-M-004 | GET /songs/、/songs/{id}/stream/ |
| REQ-04 | 收藏与管理私有歌单 | TC-M-005 | /favorites/*、/playlists/* |
| REQ-05 | 记录可信、幂等的有效播放 | TC-M-006、TC-M-007 | POST /behaviors/ |
| REQ-06 | 用双路自适应方案获得推荐 | TC-M-008、TC-M-009 | /recommendations/daily/ |
| REQ-07 | 无候选时安全回退且理由真实 | TC-M-010、TC-M-011 | /recommendations/daily/ |
| REQ-08 | 复现分组实验且没有测试泄漏 | TC-M-012 | evaluate_recommender 命令 |

完整 Given / When / Then 在 features/music.feature 与 features/boundaries.feature。页面路径固定为 /login、/register、/onboarding、/discover、/songs/:id、/favorites、/playlists、/playlists/:id、/daily；管理维护使用 /admin/，第一版不额外实现 Vue 管理后台。

页面行为：登录后未完成引导进入 /onboarding；确认选择 3—5 个标签或明确跳过后设置 onboarding_completed=true。界面允许先浏览曲库，收藏、行为与每日推荐要求登录。歌曲列表每页 20 条，可选 1—100；歌单列表按 id 升序，曲库按 id 升序。

本地播放器使用用户主动选择的 File 对象 URL，不上传；离开页面撤销对象 URL。第一版不提供本地文件与曲库 ID 自动匹配，本地播放不产生训练事件。在线播放只使用服务端 stream 地址，失败提示且不自动生成有效行为。

示例：未登录调用每日推荐得到 AUTH_REQUIRED，不静默创建游客身份。

## 第 3 部分：API 接口与契约

唯一接口定义为 openapi.yaml。前缀 /api/v1/，JSON 使用 UTF-8，路径带结尾斜杠，不依赖重定向修正 POST。ID 为正整数；时间使用 UTC RFC 3339 字符串；分数为有限数字，拒绝 NaN / Infinity。

安全：登录会话 Cookie；GET /auth/csrf/ 设置 CSRF Cookie 并返回 csrf_token；注册、登录也校验 CSRF。所有写操作校验 CSRF，所有用户资源校验所有权。Cookie 在 HTTPS 部署中 Secure、HttpOnly（session）、SameSite=Lax；开发只允许 localhost 指定来源，不使用任意跨域。

返回：成功体不加通用 data 包装；错误体为 {error_code,message,details,request_id}，details 是仅含非敏感字段名的字符串数组。无响应体端点为 204。所有响应带 X-Spec-Version: v0.1.0 和 X-Request-ID（服务器 UUID）。

示例：PUT /api/v1/me/interests/ 请求 {tag_ids:[1,2,3]}，响应 {tag_ids:[1,2,3],onboarding_completed:true}。未知字段或重复标签拒绝为 VALIDATION_ERROR，不能默默忽略。

所有参数、响应结构、状态码和 CSRF 标头见 OpenAPI。歌曲元数据允许公开查询，但流资源只允许已登录用户；登录不能赋予无许可音频播放权。管理维护通过 Django admin，不另设未定义的上传 API。

## 第 4 部分：数据模型与校验规则

entities.schema.json 是业务实体字段的唯一结构定义；API 请求与响应字段在 openapi.yaml 中定义，不允许把存储实体直接全部序列化给前端。各实体独立 Schema 文件通过 $ref 指向总定义。

通用映射：同名 JSON 字段映射同名 Python 属性及同名数据库列；*_id 为外键列，关系属性为去掉 _id 的名字；id 为 BIGINT 主键。UUID 使用 CHAR(32) 存储、接口输出带连字符字符串；date 为 DATE；date-time 为 UTC DATETIME(6)；number 为 DOUBLE；integer 为 BIGINT，时长与位置为 INT；boolean 为 BOOLEAN；有 maxLength 的 string 为对应 VARCHAR；无 maxLength 的许可说明为 TEXT；数组/对象为 JSON。JSON Schema 的 required 定义持久化快照完整性，新增时服务器生成 id 与时间；无 default 的客户端业务字段必须显式提交，null 仅在 Schema 允许时合法。

| 实体 | Schema 名称 / Python 类 | 表 | 约束与默认生成 |
|---|---|---|---|
| User | User | music_user | 继承 AbstractUser；username 唯一、ASCII 字母数字下划线 3—30；PBKDF2PasswordHasher；新注册 staff=false、origin=REAL；禁止公开 origin 修改接口 |
| Tag | Tag | music_tag | (kind,name) 唯一；name trim 后 1—30；无父标签；active 默认 true |
| Song | Song | music_song | duration_ms > 0；文件由管理员受控上传；active 默认 false，许可与音频校验通过才允许发布 |
| SongTag | SongTag | music_song_tag | (song_id,tag_id) 唯一；weight 固定 1，不设计自动标注权重 |
| UserTag | UserTag | music_user_tag | (user_id,tag_id) 唯一；0 或 3—5 条，通过事务全量替换 |
| Favorite | Favorite | music_favorite | (user_id,song_id) 唯一；保留首次 created_at；DELETE 物理删除关系 |
| Playlist | Playlist | music_playlist | name trim 后 1—60；每用户最多 100 个；服务器写入 owner |
| PlaylistSong | PlaylistSong | music_playlist_song | (playlist_id,song_id) 唯一；每歌单最多 500 首；created_at,id 升序 |
| Behavior | Behavior | music_behavior | event_id 全局唯一；(user_id,listening_session_id,kind) 唯一；origin 复制 User.origin；occurred_at=服务器接收时间 |
| RecommendationSnapshot | RecommendationSnapshot | music_recommendation_snapshot | (user_id,day) 唯一；day 按 Asia/Shanghai；revision 初始 1；原子替换 items |

外键：SongTag、UserTag、Favorite、PlaylistSong 采用 CASCADE；Behavior 与 Snapshot 的 user 外键为 PROTECT；Behavior.song 为 PROTECT。管理员通过 is_active / active 停用账户或歌曲，不直接删除已有行为关联对象。Song.file_path 只允许媒体根内相对路径，不接受管理员输入任意绝对路径或远程 URL。

日期字段由服务端生成且 API 只读。User 的框架权限字段、密码字段、last_login、date_joined 使用 Django 模型定义，禁止通过公开 API 写入。Schema 中 User 是应用可见投影，不是权限表的完整数据库描述；框架精确迁移仍是实施门槛。

示例：SongTag.song_id 对应表 music_song_tag.song_id、模型 SongTag.song_id、Schema SongTag.properties.song_id；权重值只能为 1。

## 第 5 部分：业务规则与状态流转

### 5.1 账户、收藏、歌单与媒体

注册密码长度 10—128，启用 Django UserAttributeSimilarityValidator、MinimumLengthValidator(min_length=10)、CommonPasswordValidator、NumericPasswordValidator；用户名大小写不敏感，落库前转小写，ASCII 正则 ^[a-z0-9_]{3,30}$。注册成功不自动登录；用户名冲突 409，登录失败统一 AUTH_FAILED，不区分用户不存在或密码错误。

PUT 收藏与 PUT 歌单歌曲是幂等操作，已有关系返回 204，不更新原始 created_at。DELETE 不存在的自有关系仍返回 204；访问他人歌单返回 404。添加歌曲要求 active=true，playlist 上限按事务锁后计数。管理员维护歌曲、标签与许可证明；不得通过输入许可名称绕过人工核验。

stream GET 支持单段 bytes Range；无 Range 为 200，合法单段为 206，多段或无法满足为 416，均带 Accept-Ranges: bytes；文件丢失为 503。仅允许音频 MIME audio/mpeg、audio/wav、audio/ogg；上传上限 30 MiB，后端校验文件实际类型，不信任扩展名。必须 active、playback_allowed=true、checked_at 非空且文件存在，才返回媒体内容；否则分别按第 6 部分处理。

### 5.2 行为事件与幂等

PLAY 在服务器首次收到时建立该用户/歌曲/播放会话，position_ms=0；COMPLETE 或 SKIP 必须有该用户同歌曲同 listening_session_id 的 PLAY，且该会话尚未终止。每个事件由客户端生成 event_id。重传相同 event_id 且规范化载荷一致返回已有事件 200；若任一载荷字段不同返回 409 EVENT_CONFLICT。首次接受返回 201。跨用户重复 event_id 返回同一冲突码，不披露旧事件内容。

以服务器 elapsed_ms=接收时刻减 PLAY 接收时刻，effective_ms=min(listened_ms,elapsed_ms,duration_ms)。listened_ms为必填的客户端实际播放累计时长，暂停、等待和拖动不增加该值。COMPLETE 必须 effective_ms >= ceil(0.8*duration_ms) 且 position_ms >= ceil(0.8*duration_ms)；SKIP 位置必须在0至duration_ms。只有 COMPLETE 产生正向播放反馈。PLAY 不计成熟度，SKIP只记录。累计规则与自报数据限制见implementation-boundaries.md第2节。

有效播放门槛：COMPLETE 还需 effective_ms >= min(30000,ceil(0.8*duration_ms))，前述完成门槛已保证满足；保留该定义以与短音频兼容。真实时间约束可减少跳转冒充，但不能防止所有伪造，论文不宣称反作弊完备。

示例：时长 100000ms，收到 COMPLETE 位置 90000ms，但服务器只经过 1000ms，拒绝 INVALID_TRANSITION，不记录有效播放。断网或用户关页不补造完成事件。

### 5.3 画像、User-CF 与候选

推荐只读取快照计算时刻之前的数据。在线 REAL 用户仅使用 REAL 邻居；SIMULATED 使用 SIMULATED；研究数据在独立实验库处理，不混入线上邻居。

用户—歌曲正向矩阵 R：当前有效收藏贡献 5；同一歌曲存在至少一次合法 COMPLETE 贡献 3；两者相加，上限 8。重复 COMPLETE 不累加。取消收藏去掉 5，但不会删除完成行为的 3。成熟度 n=R>0 的不同歌曲数。

对 active 标签建立歌曲单位向量 V_i：标签关联值为 1，随后 L2 归一化；零标签歌曲为零向量。初始画像 E 为用户所选 active 标签的单位向量；行为画像 B=L2normalize(Σ_i R_ui*V_i)。lambda=n/(n+10)。E、B 均非零时 P=L2normalize((1-lambda)*E+lambda*B)；只存在一个非零向量时取该向量；两者为零时 P=0。内容原分数 c_ui=max(0,cos(P,V_i))。

User-CF：用户相似度 s_uv 为 R 行向量余弦；至少 2 首共同正向歌曲且 s>0 的邻居才保留。按 s 降序、user_id 升序选 20 人。协同原分数 f_ui=Σ_v s_uv*R_vi / Σ_v s_uv，仅有对歌曲 i 产生正向贡献的邻居进入分母。无贡献为 0。

候选全集 A：active 且有已核验播放权、真实媒体文件的歌曲，排除当前收藏与过去 24 小时 COMPLETE 的歌曲。所有方法采用相同 A，不把用户喜欢过的歌曲一概永久排除。先在 A 上计算所有 c、f；这是单机有界曲库方案，不建立多路截断召回。c>0 或 f>0 的歌曲进入个性化集合 C。

分别在 A 上使用除最大值归一化：c'=c/max_A(c)，f'=f/max_A(f)；若最大值=0，则该路全部 0。不采用 min-max，避免单个正候选变成零；每路归一化只做一次，不在逐项循环内重新计算范围。

### 5.4 自适应融合与回退决策

alpha_target=0.30+0.60*10/(10+n)。n=0 时为 0.90，n 增加时单调非增，下界 0.30；固定权重对照 alpha_target=0.50。

| 内容路最大分数 | 协同路最大分数 | alpha_effective | 结果 |
|---|---|---|---|
| >0 | >0 | alpha_target | score=alpha*c'+(1-alpha)*f' |
| >0 | =0 | 1 | score=c' |
| =0 | >0 | 0 | score=f' |
| =0 | =0 | null | 全部采用 HOT |

C 按 score 降序、song_id 升序取前 20；不足 20 时从 A\C 按热度降序、song_id 升序补位。热度为该数据来源群体当前 R>0 的不同用户数，不加到融合分数。曲库不足返回实际数量，空库返回空 items 和 empty_reason=NO_ELIGIBLE_SONGS，不报 500。

CONTENT 为 c'>0,f'=0；CF 为 c'=0,f'>0；HYBRID 为两者均>0；补位为 HOT，score=0，content_score/cf_score=0。输出得分是归一化后六位小数，排序与选取使用未舍入的内部值。alpha_effective 是用户级，不是歌曲级。

解释证据：CONTENT 保存 P_t*V_it 最大的最多 2 个正贡献标签（同分按 tag_id）；行为画像标签不是用户手选标签时解释“符合你的听歌偏好”，不能写“你选择了”。CF 保存贡献用户数 neighbor_count，不输出其身份。HYBRID 同时具备两种证据。HOT 必须明确标注“热门歌曲，供你探索”，不得使用个性化措辞。解释模板固定：CONTENT“符合你的听歌偏好：{标签名用、连接}”；CF“与你偏好相近的用户也喜欢”；HYBRID“匹配{标签名用、连接}，相近偏好用户也喜欢”；HOT“热门歌曲，供你探索”。

示例：n=10，alpha_target=0.60；两路均有效且某歌 c'=0.8,f'=0.5，融合 score=0.68。

### 5.5 每日快照、并发与状态

GET daily：按上海日期查快照，无记录则计算 revision=1；有记录返回并过滤新下架、文件失效、新收藏与近24小时完成歌曲，不补位，不改变 revision。POST refresh 在事务中为当天行加锁重算、revision+1；首次 refresh 仍为1。每用户成功 refresh 间隔至少60秒，不满足429；并发首次创建依靠唯一约束重读行，禁止生成重复快照。GET 不刷新已有记录。响应禁止缓存到共享代理（Cache-Control: private,no-store）。

跨午夜生成以请求开始时刻的上海日期归档。items 有效性响应前再次核验；过滤为空仍返回200。喜欢歌曲不会暗中触发重算，页面提示可刷新且展示下一次可刷新时间。

状态机见 states.yaml。例：NONE → PLAYING → COMPLETED 后，同会话 SKIP 返回 INVALID_TRANSITION；完全相同 COMPLETE 重传优先走幂等分支。

### 5.6 规划服务签名

核心签名如下；service-contracts.md补充API、管理表单、命令、关系写入、纯计算/快照/行为边界。数据库适配/快照已在daily.py实现，record_behavior在behavior.py实现；签名变更先修订规范。

~~~python
record_behavior(*, user_id: int, event_id: str, song_id: int, listening_session_id: str, kind: str, position_ms: int, listened_ms: int, now: datetime) -> tuple[Behavior, bool]
build_user_profile(*, user_id: int, cutoff: datetime, origin: str) -> dict[int, float]
score_user_cf(*, user_id: int, candidate_ids: list[int], cutoff: datetime, origin: str, neighbor_limit: int = 20) -> dict[int, float]
calculate_daily(*, user_id: int, now: datetime, limit: int = 20) -> list[RecommendationItem]
get_daily(*, user_id: int, now: datetime) -> RecommendationSnapshot
refresh_daily(*, user_id: int, now: datetime) -> RecommendationSnapshot
~~~

### 5.7 离线评价协议

五组方法：HOT、CONTENT、USER_CF、FIXED、ADAPTIVE。每组共用可用曲库、过滤与热门补位规则，固定 K=10；固定融合 alpha=0.5，自适应按5.4。不调节测试集参数。采用真实时间戳时按全局时间排序，前70%训练、随后10%验证、最后20%测试，分界同一时间戳全部归入后段；若导致任一分区空则终止该协议并报告原因。

标签必须在训练截止前已可获得，或由独立内容人工标注且不查看测试行为；画像、用户相似度、热度只用训练集。参数版本为当前固定值，不做验证集调优；如果修改参数，先记录候选集合并仅用验证集选择。测试目标为测试期正向交互中训练期未正向交互的歌曲集合，候选为训练期已发布且合法研究可用曲目，排除训练正向歌曲；实验可不要求可播放文件，但各方法一致，并明确与演示曲库区别。

Precision@10=命中数/10（不足10不缩小分母）；Recall@10=命中数/目标数；Hit@10=是否命中至少1首；NDCG@10 用二值相关度及 log2(rank+1)，IDCG 取 min(10,目标数)。无目标用户不参与上述平均，单独报告数量；有目标无推荐按0计入。Coverage=全部被推荐歌曲并集数/共同候选曲库数；分母0输出null与原因。

冷启动组隐藏目标用户全部历史并从邻居矩阵移除该用户，只允许使用测试前真实独立记录的兴趣；没有该兴趣数据，不报告“真实标签冷启动提升”，只报告模拟结果。正常组按训练不同正向歌曲数分为1—9、10—29、>=30，0行为单列冷启动。真实和模拟报告分别生成，不合并平均。

命令规划：python manage.py evaluate_recommender --dataset <manifest.json> --output <directory> --seed 42。manifest 必须声明来源、许可证据、origin、字段映射、时区和时间戳真实性。没有真实时间戳时退出码2并说明原因，本协议不自动使用随机切分替代。

### 5.8 本轮补齐的边界

implementation-boundaries.md为第4至第6部分的规范性补充，固定分页越界、停用标签与下架歌曲、null触发条件、暂停/拖动、错误检查优先级、锁顺序和补充服务签名；若前文概述与补充冲突，以该补充的明确规则为准。数据库方案仍是MySQL 8.x；environment.md记录本机9.2.0，仅为观察，不自动改变目标版本。

## 第 5 部分附：Properties 行为不变量

| 性质 ID | 回链 | 可判定公式 | 生成器 | 自动化 ID |
|---|---|---|---|---|
| P-M-01 | REQ-05 / TC-M-006 | 相同event_id与载荷重复m>=1次 ⇒ 行数=1、结果id相同 | 1—100次重复事件 | PT-M-001 |
| P-M-02 | REQ-06 / 5.4 | 0<=n1<=n2 ⇒ .3<alpha(n2)<=alpha(n1)<=.9 | n取0—100000整数 | PT-M-002 |
| P-M-03 | REQ-07 / 5.3 | 任意输出列表 ⇒ ID不重复且全部属于过滤后A | 0—300歌曲与布尔许可/发布状态 | PT-M-003 |
| P-M-04 | REQ-07 / 5.4 | HOT ⇒ 标签证据空且邻居数0；HYBRID ⇒ 标签证据非空且邻居数>0 | 四类正负贡献组合 | PT-M-004 |
| P-M-05 | REQ-01 / REQ-04 | user!=owner ⇒ 私有歌单读写返回404且数据不变 | 两个不同用户及私有歌单 | PT-M-005 |
| P-M-06 | REQ-06 / 5.4 | 固定输入与时间 ⇒ 推荐顺序与未舍入分数相同 | 同输入随机置换读取顺序 | PT-M-006 |

P-M-07至P-M-12的公式、生成器和PT映射见properties.md，覆盖兴趣替换、刷新限流、发布、关系写入、终止状态与事务回滚。

全部未自动化；期限为对应实现任务完成前。仅在变更命中该性质、oracle、生成器或其实现时运行对应 PT，不把路径检查视为性质测试通过。

## 第 6 部分：错误处理与日志规范

| 错误码 | HTTP | 触发条件 | 日志级别 |
|---|---|---|---|
| VALIDATION_ERROR | 400 | 字段缺失、未知、类型或范围错误 | INFO |
| AUTH_REQUIRED | 401 | 未登录访问保护资源 | INFO |
| AUTH_FAILED | 401 | 登录失败 | INFO |
| CSRF_FAILED | 403 | 写请求CSRF错误 | WARN |
| PERMISSION_DENIED | 403 | 非管理员访问管理入口或无播放许可 | WARN |
| NOT_FOUND | 404 | 不存在、下架歌曲或他人私有资源 | INFO |
| USERNAME_TAKEN | 409 | 注册用户名冲突 | INFO |
| EVENT_CONFLICT | 409 | 事件ID载荷冲突或相同会话类型重复 | INFO |
| INVALID_TRANSITION | 409 | 缺PLAY、会话已结束或完成时间不足 | INFO |
| LIMIT_REACHED | 409 | 歌单数量或歌曲数超限 | INFO |
| RATE_LIMITED | 429 | 60秒内重复刷新 | INFO |
| MEDIA_UNAVAILABLE | 503 | 合法发布歌曲的文件不存在 | ERROR |
| INTERNAL_ERROR | 500 | 未处理异常，事务回滚 | ERROR |

媒体 Range 无法满足返回416与 Content-Range: bytes */文件长度，不返回JSON；无权限先于Range解析检查。其余错误体遵循OpenAPI，500不返回堆栈。日志JSON字段固定为request_id、user_id（匿名为null）、action、status、error_code、elapsed_ms。推荐重算额外记录algorithm_version、revision、candidate_count、origin，不记录密码、会话Cookie、CSRF token、音频内容或邻居身份。保留7天，删除仅针对明确配置的日志目录并遵守工作区删除授权。

示例：事件冲突记录error_code=EVENT_CONFLICT，不记录旧事件载荷。所有数据库写入在事务中，失败不能产生半条收藏或半份快照。

## 第 7 部分：测试覆盖矩阵

| 需求来源 | 需求 ID | 类型 | 测试用例 ID | 自动化状态 |
|---|---|---|---|---|
| 2 / 5.1 | REQ-01 | 验收 | TC-M-001、TC-M-002 | Django对应测试通过；Gherkin与MySQL未验收 |
| 2 / 5.3 | REQ-02 | 验收 | TC-M-003 | Django对应测试通过；Gherkin与MySQL未验收 |
| 2 / 5.1 | REQ-03 | 验收 | TC-M-004 | 内存合成音频Range/许可拦截通过；真实授权音频/浏览器未验收 |
| 2 / 5.1 | REQ-04 | 验收 | TC-M-005 | Django顺序幂等测试通过；MySQL并发未验收 |
| 2 / 5.2 | REQ-05 | 验收 | TC-M-006、TC-M-007 | Django事件幂等/拖动反例通过；Gherkin/MySQL/浏览器未验收 |
| 2 / 5.3—5.5 | REQ-06 | 验收 | TC-M-008、TC-M-009 | 0.68计算oracle与无邻居API通过；MySQL及Gherkin未验收 |
| 2 / 5.4 | REQ-07 | 验收 | TC-M-010、TC-M-011 | 空库与HOT的Django API/Schema测试通过；MySQL及Gherkin未验收 |
| 2 / 5.7 | REQ-08 | 验收 | TC-M-012 | 未自动化：无实验程序，T06完成前 |
| 5.8 / 实施边界2 | REQ-05 | 验收 | TC-M-013 | 暂停自报低时长的Django反例通过；浏览器累计未验证 |
| 5.8 / 实施边界1 | REQ-03 | 验收 | TC-M-014 | Django对应测试通过；Gherkin与MySQL未验收 |
| 5.8 / 实施边界1 | REQ-04 | 验收 | TC-M-015 | Django对应测试通过；Gherkin与MySQL未验收 |
| 5.8 / 实施边界3 | REQ-01 | 验收 | TC-M-016 | 每日刷新CSRF先于认证的Django测试通过；Gherkin未绑定 |
| completion-contract.md 2 | REQ-03 | 验收 | TC-M-017、TC-M-018 | 空/超限/截断/路径/MP3-OGG人工核验表单测试通过；真实浏览器预览未验收 |
| OpenAPI全部operationId | REQ-API | 契约 | CT-M-001 | 部分响应Schema已验证；24操作全部分支未完成 |
| P-M-01 | REQ-05 | 属性 | PT-M-001 | 相同载荷顺序100次重传通过；MySQL并发未测 |
| P-M-02 | REQ-06 | 属性 | PT-M-002 | 纯计算n=0—100000权重测试通过 |
| P-M-03 | REQ-07 | 属性 | PT-M-003 | 纯计算16种资格组合及0—300歌曲有界测试通过；实际媒体适配未验证 |
| P-M-04 | REQ-07 | 属性 | PT-M-004 | 四来源计算证据与解释测试通过；线上数据适配未验证 |
| P-M-05 | REQ-01 | 属性 | PT-M-005 | 已有私有歌单读写隔离测试通过；完整生成空间未覆盖 |
| P-M-06 | REQ-06 | 属性 | PT-M-006 | 纯计算固定seed输入20次置换稳定性通过 |
| properties.md P-M-07 | REQ-02 | 属性 | PT-M-007 | seed=42顺序测试通过；完整生成空间未覆盖 |
| properties.md P-M-08 | REQ-06 | 属性 | PT-M-008 | 顺序0/59/59.01/60/61秒与午夜测试通过；MySQL并发未测 |
| properties.md P-M-09 | REQ-03 | 属性 | PT-M-009 | 32种发布条件及内存字节边界通过；真实文件/浏览器/完整空间未验收 |
| properties.md P-M-10 | REQ-04 | 属性 | PT-M-010 | 顺序重试与满容量测试通过；完整生成空间未覆盖 |
| properties.md P-M-11 | REQ-05 | 属性 | PT-M-011 | COMPLETE/SKIP终止、新事件拒绝与原事件重传通过；完整生成空间未覆盖 |
| properties.md P-M-12 | REQ-01 | 属性 | PT-M-012 | 兴趣/快照/行为故障回滚通过；完整关系与并发空间未完成 |
| migration-design.md | REQ-DB | 数据库 | DB-M-001、DB-M-002、DB-M-003 | 未自动化：T02/T04完成前 |
| 8 | REQ-NFR | 性能与安全 | NF-M-001 | 未自动化：T06完成前 |

例如PT-M-002覆盖单调性，不代表推荐质量提高；CT-M-001应枚举每个operationId的成功和错误响应，不能只测接口存在。

## 第 8 部分：非功能性需求

| 类别 | 目标 | 验证方法 |
|---|---|---|
| 性能 | 1000歌、300用户、每人30个正反馈、20并发下每日GET P95<=1000ms；重算P95<=5000ms | NF-M-001在单机预热后运行200请求，记录CPU、内存、版本与P95；不当作当前实测 |
| 数值 | 所有推荐分数有限且在[0,1] | PT-M-002、CT-M-001检查边界与零向量 |
| 权限 | 私有歌单跨用户访问全部404，CSRF失败全部403 | TC-M-002与CT-M-001穷举写操作 |
| 可靠性 | 同事件100次重试只生成1行，回滚后无部分写入 | PT-M-001及事务故障注入 |
| 版权 | 每首可播放曲目100%具备来源、许可、核验时间与允许播放标记 | 发布前管理员清单检查与TC-M-004 |
| 可复现 | 同数据摘要、参数、seed=42与cutoff得到相同排序 | PT-M-006与TC-M-012 |

示例：未达到重算性能目标时先报告样本和瓶颈，不能自行引入Redis或改变算法语义。v0.1.0不提供公共互联网服务，不承诺可支持大规模用户。

## 第 9 部分：假设、约束与变更日志

外部假设：学校未提供强制模板与截止时间；本机解释器、命令与数据库服务已核验，结果见environment.md，但项目依赖锁、数据库连接/兼容性仍未核验；合法音频与真实研究数据尚未取得。数据库实机为9.2.0，与8.x目标存在差异，需明确批准兼容验证方向，不自动更改既有实例。

约束：Vue / Django / MySQL技术方向已确认；本版不含Redis、Celery、商业平台接口、深度学习、实时场景识别、MMR和Item-CF。24个API、管理/媒体/行为/推荐后端及九类前端页面与单播放器已实现，后端181项及前端46项离线测试通过；真实授权文件发布/播放、MySQL迁移/并发、浏览器计时与CI未验收，最新结果见workflow-results.md，实机前提见live-acceptance.md。

变更日志只从真实Git记录生成；当前无Git，以下保持空表，不手写不存在的提交。

| 日期 | 版本 | 变更说明 | 关联 Commit |
|---|---|---|---|

示例：当前没有Commit和Tag；v0.1.0只表示本提议文档版本，不代表发布版本。
