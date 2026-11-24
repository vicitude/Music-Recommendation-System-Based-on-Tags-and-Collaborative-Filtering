# 服务与管理入口精确定义

## 第一阶段个人中心：播放历史

`getHistory(request: Request) -> Response` 对应受会话认证的 `GET /api/v1/me/history/`，停用或匿名账号返回 401 AUTH_REQUIRED。仅查询 request.user 已接受且持久化的 Behavior.PLAY，不使用 COMPLETE/SKIP，也不按他人记录更新最近时间。仅展示与公开曲库相同的 active=True 歌曲；不可播放但仍公开的歌曲保留，由既有 SongSerializer 决定 playable/stream_url。

按歌曲去重取 MAX(occurred_at)，稳定按 last_played_at 降序、song.id 升序；过滤与去重先于计数和分页。返回严格结构 `{items: [{song: Song, last_played_at: ISO8601}], total, page, page_size}`；song 为现有完整前台结构（含当前用户 current_rating 与有效标签），不暴露 file_path、用户或会话标识。与前端 worker 约定一致，不采用曲库的 count/results 键。

仅接受单值 page（默认 1），每页固定 20，响应 page_size 恒为 20；page_size 参数一律拒绝；非法、重复或未知参数返回 400 VALIDATION_ERROR。空集 page=1 返回 200 空 items；超过末页返回 404 NOT_FOUND。非 GET 方法返回 405。读取不写行为、歌曲、用户、推荐快照或刷新限流，不调用推荐生成；无模型变更、迁移或真实库操作。自动化覆盖见 backend/music/test_history.py；内存测试不代表 MySQL 或浏览器验收。

管理员推荐诊断（2026-11-02）：GET /admin/music/user/recommendation-diagnostics/，活跃staff且具有view_user与view_song权限才可访问；其他方法405，不暴露公开API。用表单user_id选择活跃账号（按ID排序），不默认计算、不写用户/行为/快照，不刷新每日推荐或重置限流。非法ID显示中文400，数据库/算法异常脱敏显示503，参数不接受密码或任意文件路径。

build_diagnostics(user_id:int,now:datetime)->dict调用既有load_inputs及recommend(limit=DAILY_LIMIT=10)，当前时刻只读试算，复用同origin隔离、候选过滤和打分；显示兴趣标签、正反馈去重歌曲数（收藏/有效COMPLETE）、同源活跃用户数、目标alpha与实际alpha、标签/协同占比、路由/降级说明。结果逐首含名称/歌手、来源、归一化content_score/cf_score、融合score、贡献邻居数、证据标签及原始解释。明确0—1分数非概率、贡献邻居是针对每首候选而非全局用户数、至少2首共同正反馈才可能成为相似用户，没信号不虚构。

仅显示最新既有快照日期/revision/算法版本/生成时间/条数（没有则说明），不调用get_daily/save_generation、不声称重现历史计算。当前数据变化可能令试算与快照不同；不把当前alpha或标签解释嫁接到旧快照。checked_at仅现有发布状态，不声称试听。无新模型/迁移/依赖，诊断请求Cache-Control private,no-store。测试覆盖管理员/普通/越权staff、方法/参数、无快照写入、冷启动/热门/协同混合及分数等于原引擎输出、同源隔离、空候选与脱敏异常。

2026-11-02收藏交互：SongList挂载/账号变化后通过既有favorites分页API(page_size=100)读取当前收藏ID，匿名不请求；成功读取前禁用收藏写入，失败显示重试按钮。不扩展API字段。空心爱心+收藏，已收藏为红色实心爱心+已收藏，aria-pressed同步；点击已收藏切换DELETE，未收藏PUT，写成功才更新本地ID集合，失败保持原状态。账号变更/卸载的旧请求不能更新新账号视图。推荐/发现页收藏不触发changed重载，不隐藏歌曲、不重排，推荐手动刷新时才应用后端排除收藏规则；收藏页取消后仍触发changed更新集合。收藏状态初次读库支持刷新/翻页，与后端最终一致，不在浏览器存储凭据。保留写请求去重，歌单移除原行为不变。

2026-11-02列表与推荐数量：SongList增加可选indexOffset（默认0），无显式推荐rank时显示indexOffset+index+1；Discover按服务器返回(data.page-1)*data.page_size传入，不按正在加载的请求页推算，搜索重置第1页。每日推荐生成默认10首（算法内部最大20及协同邻居数不变），序列化先执行既有可用性/证据过滤再取前10首并连续rank，旧20首快照也最多返回10首、不重写数据库。候选不足不凑满5首，可少于5或空；无新增配置/依赖/迁移，不改变排序打分和刷新限流。页面说明最多10首。

注册页面错误可读性（2026-11-02）：保持注册API/密码校验不变，不声称仅凭截图确认实际失败原因。前端用户名trim后验证3—30位ASCII字母/数字/下划线；密码原样保留，前置长度10—128及非纯数字，两次一致校验；不阻止正常空白密码字符。页面常驻显示后端规则：不能纯数字、过于常见或与用户名太相似，不要求一定含特殊字符。后台VALIDATION_ERROR按details中的password/username显示对应中文规则（密码提示列出可能原因而非伪造准确原因），USERNAME_TAKEN提示更换用户名；其他错误沿用原消息。提交失败保留输入，不记录密码，成功清空两密码并跳登录，不自动登录、不更改安全策略。测试覆盖前置拒绝、字段错误、用户名重复、成功载荷与跳转、后端真实注册及密码验证。

歌曲标签重复校验（2026-11-01）：SongTagInline使用自定义BaseInlineFormSet。clean在数据库保存前校验非删除行tag_id唯一，重复显示中文行内错误及汇总，不更新歌曲或发布状态；数据库已有但本次未提供的关系仍计入冲突。若把已有标签改成另一个仍占用的标签（含交换两行），提前提示先保存移除再添加，避免数据库唯一约束在逐行更新期间冲突。删除行不参与最终去重，保存现有对象时先执行全部授权删除再更新，支持“删除旧行并重新添加同标签”。保留uq_song_tag约束，不清理真实数据、不把编号推测为具体标签名。回归覆盖重复新增、已有标签再新增、改选冲突、交换、删除重加、无重复正常保存及失败不发布。并发数据库故障不在本条中泛化吞掉。

后台分页样式（2026-11-01）：仅覆盖#changelist .paginator，当前页span.this-page使用深色背景#44394f和白字#fff8f0，其他页a:not(.showall)使用浅底#eee6dd和深字#302937，hover/focus使用浅强调#f9e2d5，不伪装当前页；显示全部保留普通链接。两种主题下选中语义一致，保留原生焦点提示。CSS版本20261101-2；不改页码、查询参数、筛选或分页数据。测试验证40首歌曲的第1/2页当前标记与链接及样式声明，不以静态测试代替实际视觉复验。

状态：开发中。与spec.md第5.6节、implementation-boundaries.md互补；API视图的24个精确名称、参数、请求Schema和响应状态见[api-bindings.json](api-bindings.json)。24个操作及媒体管理、行为/推荐服务已实现；真实媒体、MySQL、前端与完整契约未验收，最新见[媒体验证](media-results.md)。

## 歌曲后台移除来源许可填写流程（2026-11-01）

### 后继规则：一键发布及标签CRUD

本条取代旧手工播放开关、试听复选框和时间填写规则。歌曲编辑底部提供POST提交按钮_publish（保存并发布）、已发布歌曲提供_unpublish（保存并下架）；普通保存保持当前发布状态，新建默认为草稿。表单排除active/playback_allowed/checked_at，不信任同名POST，移除preview_confirmed。发布或保存已发布歌曲须验证受控音频存在、大小/结构、MIME与有效时长（WAV差不超过1000ms）；新上传MP3/OGG可一次保存并发布，不声称服务器已完整解码或人工试听。成功保存时active/playback_allowed同步为True，checked_at记录服务器发布时间（不再表示试听证明）；普通保存不更新既有时间，下架同时关闭两标志，保留时间。请求同时带发布/下架拒绝，所有校验在写入前，歌曲及标签使用既有admin事务，CSRF/模型权限保留。

标签CRUD使用既有/admin/music/tag/：搜索/分类筛选、新增、编辑及Django原生删除确认；delete_tag权限才允许删除，保留确认页关联影响展示和CSRF，GET不删除，不自动删除任何现有数据。Tag删除级联移除SongTag/UserTag、不删除歌曲/音频/行为，历史JSON推荐快照保留，失效解释由现有serialize_daily过滤，刷新后重新计算。SongTagInline允许具有delete_songtag权限者在歌曲编辑页删除单条关联（不删全局标签），仍禁止删除Song。标签修改不会自动重建已生成每日快照，须刷新推荐，前台曲库标签查询立即使用新值。无迁移/新依赖；实际删除必须由用户在确认页面提交，本轮不代操作真实库。

按用户要求移除歌曲编辑页“来源与许可”区块及rights_confirmed字段，不改为折叠或隐藏必填输入。SongAdminForm排除source_name/source_url/license_name/license_url/attribution_text/redistribution_allowed，既有数据库值保留，伪造POST不得修改这些值；新增记录沿用模型空字符串/False默认，不写虚构许可或来源。删除URL及许可必填校验，发布不再要求填来源链接、许可名称/链接或确认许可；此条取代下文及历史规格中相冲突的旧后台门槛，仅影响后台填写流程，不作为法律授权或许可核验结论。

保留有效受控音频、真实时长/MIME一致性、playback_allowed（显示为“开启前台播放”）、checked_at（显示为“试听核验时间”，不可未来）、MP3/OGG先草稿后试听确认等校验。区块“播放与上架”仅含播放开关、试听确认、时间、active。不自动发布既有草稿，不改受控流/权限/路径规则、去重指纹、库结构或历史数据，不新增迁移或依赖。后台工作台说明同步为音频试听/上架流程，不再提示填许可。验收覆盖页面无原区块/输入、既有信息保留与恶意POST忽略、新建空来源有效音频可发布、缺音频/未试听/未开播放仍拒绝、草稿标签保存不回归。

## 标签可读名称与常用词表

单选下拉可读性：自定义admin.css在Django样式之后覆盖select:not([multiple])的固定高度，设置height:auto、min-height:44px、line-height:1.5、padding:8px 36px 8px 12px，保留原生箭头/键盘选择与焦点。歌曲标签单选限定宽度24rem、max-width:100%、min-width:0，不作用于多选控件；不得通过减小用户缩放或隐藏文字规避。CSS缓存版本更新为20261101-1，回归验证自定义资源加载顺序、上述声明、真实歌曲编辑页标签控件及多选排除。截图为修复前裁切证据，静态测试不宣称已完成浏览器视觉复验；不改库、不改标签值或发布状态。

Tag.__str__返回“类型中文｜名称”（例如风格｜流行），停用项追加“（已停用）”，括号数字仅数据库ID不是含义。SongTag.__str__复用所关联标签名称（未绑定时返回“未选择标签”）。SongTagInline的tag选择按STYLE/MOOD/SCENE分组、同组按name/id排序，保留既有停用项可见但明确标识；不更改字段、关系或迁移，额外展示一行空白选择，权重仍为1。

草稿标签保存无需来源许可字段；当前发布规则以上述“移除来源许可填写流程”为准。既有删除权限仍禁用。

新增固定正式词表music/tag_library.py，提供曲风27、情绪15、后台标准场景11项及中文解释（共53项）；前台扩展场景和历史旧标签通过兼容映射处理，不混入正式词表。词表不宣称穷尽所有音乐分类、不作为已听辨结果。常用词表不自动写库、不自动绑定歌曲。歌曲曲风建议1—2项、情绪1—3项、场景0—3项；允许未知留空，避免同义词堆叠，不预先标记人工核对完成。

TagAdmin增加GET/POST `/admin/music/tag/library/` 与标签列表/歌曲标签帮助入口。活跃staff且具有view_tag/change_tag/change_song任一权限可GET，POST还必须有add_tag；GET只查询不写入，POST须CSRF、confirm_library=yes及非空selected键列表。键固定为“kind:name”，未知键或超过53项拒绝、去重；在原子事务内get_or_create(kind,name,defaults={active:True})，已存在项不修改（包括保持停用状态）、不删旧标签、失败回滚本批新建，结果显示新建/跳过数量。没有add_tag权限只能查看说明，不能提交。错误信息脱敏，不返回数据库异常。

页面列出全部53项解释与当前可用/停用/未入库状态，无默认勾选，提供显式选择全部未入库项按钮；保存仅扩充选项，之后在歌曲编辑页选择具体标签。列出既有非词表自定义项，避免用户误认为词表外标签无效。此入口不修改Song/SongTag/UserTag或推荐快照、不发布音频，不连接真实数据库代操作、不新增依赖。测试覆盖53项唯一/长度、旧候选兼容映射、中文标签分组、权限/CSRF、未知输入、去重及回滚，内存测试不替代真实后台复验。

## 本机草稿音频批量关联

后台GET/POST `/admin/music/song/local-audio/` 仅允许活跃staff且有change_song权限；POST保留CSRF校验，必须confirm_audio=yes。只读取固定local-catalog.json及固定目录D:/AAA素材库/song，不接受请求指定路径。GET只查资料及关联状态，不读取音频、不写库。仅支持已导入且source_name为LOCAL_DRAFT_SHA256:<hash>的唯一草稿；未导入、重复标记、已发布或已核验条目拒绝，已有file_path始终跳过（即使原关联文件缺失）。

POST选择非空清单指纹集合；无效选择整批拒绝。逐首独立事务并锁定歌曲行，成功项保留，失败项不影响其余，页面明确显示成功/跳过/失败及条目原因，不宣称整批回滚。每次只读一个文件，解析后须是固定目录直接子文件，拒绝符号链接及越界，大小须与清单bytes一致且1..30MiB，读取上限30MiB+1；sha256一致并通过既有MP3结构校验后，用store_audio的随机独占文件名复制入MEDIA_ROOT，仅更新file_path及mime。不修改标题、标签、发布/播放/转载标志、checked_at或许可字段；不删除、不移动、不改写源文件。结构检查不等于实际解码。

磁盘与数据库不能跨资源事务：数据库提交失败时保留已写副本，日志记录相对路径，页面说明可能有未关联副本，不自动删除；不泄露原始数据库错误。复制期间写入失败也可能保留不完整文件。完成后通过既有管理员受控预览链接试听、核对标签，前台推荐/播放仍需另行发布核验。服务bind_local_audio(items, selected_hashes, source_root=None)供固定入口调用；source_root仅内部测试注入，不从HTTP传入。测试使用临时合成音频与内存SQLite，不代表用户MySQL或真实浏览器验收。

## API视图

module固定backend/music/api/views.py，DRF函数视图以operationId作为Python函数名。路径整数转换由路由处理，不能转换的路径404；未声明方法返回405并带Allow头；非JSON请求体返回415；两者error_code固定为VALIDATION_ERROR，details分别为["method"]与["content_type"]。该路由层通用错误规则不增加已声明方法的响应分支。

所有业务错误通过ApiError(error_code: str, details: list[str] | None = None) -> None构造，details=None输出[]。统一message按错误码映射，不返回数据库原始异常。认证、CSRF、结构、对象与状态检查顺序遵守边界补充。APIView不直接访问私有关系，所有写入委托服务。

## 服务签名与返回

- register_user(*,username:str,password:str,now:datetime)->User：返回用户对象；注册不登录，清除输入密码后不得记录日志。
- authenticate_user(*,request:Request,username:str,password:str)->User：统一失败AUTH_FAILED；成功login并轮换CSRF token。
- logout_user(*,request:Request)->None：销毁当前登录会话。
- set_interests(*,user_id:int,tag_ids:list[int])->list[int]：事务替换，返回排序后的当前ID，不存在或停用标签400；成功设置onboarding_completed=True。
- set_favorite(*,user_id:int,song_id:int,present:bool)->None；set_playlist_song(*,user_id:int,playlist_id:int,song_id:int,present:bool)->None：成功无返回值。
- create_playlist(*,user_id:int,name:str,now:datetime)->Playlist；rename_playlist(*,user_id:int,playlist_id:int,name:str)->Playlist；delete_playlist(*,user_id:int,playlist_id:int)->None。
- record_behavior签名以spec.md第5.6节为准，tuple第二项为created：True对应201，False对应200。
- calculate_daily(*,user_id:int,now:datetime,limit:int=20)->list[RecommendationItem]：limit接口不暴露，只允许1—20；alpha由独立权重函数确定，快照负责存储相同输入下的值。
- content_weight(*,positive_song_count:int)->float：拒绝负数，输出spec.md第5.4节公式值。
- get_daily与refresh_daily支持可选scene_id；未传时优先使用用户唯一场景标签，否则按Asia/Shanghai时段默认场景。场景与来源、命中率、三路权重写入RecommendationSnapshot；投影由serialize_daily(*,snapshot:RecommendationSnapshot,user_id:int,now:datetime)->dict生成，过滤并重新编号，不写回revision。
- resolve_media(*,song_id:int,user_id:int)->tuple[Path,str,int]：校验授权与文件，返回受控绝对路径、MIME及字节数；不接受客户端输入路径。

补充签名覆盖原边界文档中的同名入口；create_playlist以本文件含now的版本为准。所有业务使用timezone-aware datetime，拒绝naive时间；每个请求由中间层产生一个now并向下传递。

## 行为采集执行边界

实现位置`backend/music/behavior.py`，record_behavior沿用第5.6节签名；新增recordBehavior接口只读request.now，拒绝query和额外字段，响应严格为{id,event_id,effective_ms}，首次201、完全重传200。

- `BehaviorRequestSerializer`拒绝隐式类型转换：UUID必须为trim后的36位带连字符字符串，大小写归一后入库；不额外限制UUID版本。song_id为正整数，position_ms/listened_ms为0—86400000整数，bool/float/string均不算整数；kind为trim后的PLAY/COMPLETE/SKIP。服务直接调用也执行同一结构校验，拒绝naive now。
- 顺序为结构校验→事务锁当前有效User→全局event_id检查→active歌曲→会话绑定/终止/种类→歌曲时长/载荷检查→事务插入。完全相同载荷指user、song_id、listening_session_id、kind、position_ms、listened_ms一致；now、服务器effective_ms与用户后来origin变化不作为重传载荷。跨用户event_id或任一载荷不同为EVENT_CONFLICT；完全重传优先于下架或会话终止检查。
- 会话存在其他song_id为INVALID_TRANSITION；已有COMPLETE/SKIP后任何新终止事件（即便同kind不同event_id）为INVALID_TRANSITION。尚在播放的同kind新event_id为EVENT_CONFLICT；第二个PLAY也不能重置计时。会话已终止后新PLAY仍为EVENT_CONFLICT，重新播放必须新session_id。没有PLAY的COMPLETE/SKIP为INVALID_TRANSITION。这一终止分支优先于同kind唯一关系检查，统一原边界第3节第4项与P-M-11的判定。
- PLAY的position_ms/listened_ms必须均为0，非0返回400 VALIDATION_ERROR对应字段；position_ms超过歌曲duration_ms返回400。listened_ms允许超过duration但不超过全局86400000上限，effective按duration限幅；不强行要求position=listened。COMPLETE完成门槛用整数ceil(4*duration/5)，有效时长取min(listened_ms, floor((now-PLAY.occurred_at)/1ms), duration)。负elapsed拒绝INVALID_TRANSITION而非写负值；SKIP无需满足80%，但必须有PLAY且终止会话。
- 新事件只要求歌曲active，媒体播放权在stream入口处理，本轮不添加行为端隐式媒体权限规则；服务不能证明事件来自真实播放器，必须保留自报限制。origin与occurred_at分别复制User.origin和请求now，不接受客户端赋值。PLAY/SKIP不增加推荐成熟度；只有合法写入的COMPLETE可供推荐读取。
- 插入用嵌套savepoint；IntegrityError后重读event_id和会话，已存在冲突转EVENT_CONFLICT/INVALID_TRANSITION，完全同载荷返回原事件；无法归因的IntegrityError继续抛给统一500处理，不伪装成功。User锁和唯一约束实现不代表MySQL并发已实测。

验证记录覆盖TC-M-006/007/013、PT-M-001/011与行为故障回滚；只在内存库使用合成曲目，不上传/播放音频、不连接MySQL。客户端playing时累计、暂停/拖动冻结与同event_id重试仍待前端播放器实现，不能用后端测试宣称已验证浏览器计时。

## 纯推荐计算边界

`backend/music/recommendation.py`承载不依赖Django、数据库、文件读取或网络的计算引擎。该层不替代上述规划中的数据库服务；适配层尚未完成时，不实现假数据API。固定输入/输出如下：

- `TimedSong(song_id:int,occurred_at:datetime)`表示一个收藏或完成事实；时间必须aware。`UserSignals(user_id:int,origin:str,interest_ids:tuple[int,...]=(),favorites:tuple[TimedSong,...]=(),completions:tuple[TimedSong,...]=())`。favorites只含当前仍存在的收藏，不能用已取消收藏的历史记录；completions只含已由行为服务校验通过的COMPLETE，不接受PLAY/SKIP。origin只能REAL或SIMULATED。兴趣为当前快照，不从行为推断成“用户手选”。
- `SongFeatures(song_id:int,tag_ids:tuple[int,...]=(),active:bool=False,playback_allowed:bool=False,checked:bool=False,file_exists:bool=False)`表示计算时刻歌曲状态；后三项为后续受信适配层的实际媒体/许可检查结果，不能由公开请求赋值。checked包括已完成本版规定的媒体和人工核验，不代表算法能够核验版权或解码。未核验默认全部不进入候选。active_tags为只包含active标签的`dict[int,str]`，名称长度1—30。
- `RecommendationResult(items:list[RecommendationItem],alpha_target:float,alpha_effective:float|None,empty_reason:str|None,route_weights:dict[str,float])`为内部结果，不含快照日期/版本/刷新时间；不得直接当作Daily API响应。`route_weights`固定包含content、user_cf、item_cf，实际可用路由权重和为1，无可用个性化路由时全为0。RecommendationItem结构完全复用实体Schema。空候选empty_reason=NO_ELIGIBLE_SONGS，否则null；HOT项仍属于非空候选。
- `recommend(*,user_id:int,now:datetime,songs:tuple[SongFeatures,...],users:tuple[UserSignals,...],active_tags:dict[int,str],limit:int=20)->RecommendationResult`；limit为1—20整数，bool不算整数。歌曲与用户ID唯一，ID为正整数；目标用户必须存在；无效纯计算输入抛ValueError，不自创公开错误码。
- `content_weight(*,positive_song_count:int)->float`采用第5.4节公式，拒绝负数、非整数与bool。`positive_matrix(*,users:tuple[UserSignals,...],cutoff:datetime,origin:str)->dict[int,dict[int,float]]`仅接纳同来源且occurred_at严格小于cutoff的当前收藏、合法完成事实和正向评分；同一反馈类型按歌曲去重，不重复累加；不同反馈类型按固定映射相加（收藏5、完成3、评分4/5分别为4/5）。
- `compute_profile(*,interest_ids:tuple[int,...],positive_scores:dict[int,float],song_vectors:dict[int,dict[int,float]])->dict[int,float]`实现第5.3节画像。历史正反馈歌曲不在歌曲特征集中时，仅其内容向量为零，不删除其CF维度或成熟度贡献。
- `compute_cf(*,user_id:int,matrix:dict[int,dict[int,float]],candidate_ids:tuple[int,...],neighbor_limit:int=20)->tuple[dict[int,float],dict[int,int]]`返回候选原始协同分数及实际贡献邻居数量；共同歌曲至少2，按相似度降序/user_id升序取最多20人，每首歌分母只含对该歌正向贡献的邻居。
- `fuse_candidates`支持兼容参数`cf_scores/neighbor_counts`，正式参数为`user_cf_scores/item_cf_scores`及各自贡献数；三路分别按完整候选集最大值归一化。内容路使用alpha_target，两个协同路由平分剩余权重；缺少一路时剩余路由自动归一化。`cf_score`保留为两种协同归一化分的兼容合并值，并新增`user_cf_score/item_cf_score`。来源可为CONTENT、USER_CF、ITEM_CF、HYBRID或HOT，旧CF仅用于读取历史快照兼容。热门补位不改变个性化得分和路由权重。

候选排除严格小于now的当前收藏与`now-24h <= occurred_at < now`的完成事实；早于窗口的完成不永久排除。只有同origin群体参与CF和热度。浮点加总使用按ID固定次序的math.fsum，零向量不除0，余弦裁剪到[0,1]；禁止先round再排序。标签证据按P_t*V_it降序、tag_id升序取前2。所有输入顺序的置换不得改变输出。引擎不读取文件，file_exists仅是适配层检查结果；本轮合成输入测试不能证明真实媒体可用、MySQL兼容或推荐质量提升。

本层验证使用`backend/music/test_recommendation.py`与标准库unittest；覆盖TC-M-008/009/010/011的计算部分以及PT-M-002/003/004/006的有界随机测试。HTTP、快照、来源读取与真实素材过滤必须在适配层完成后另测，不提前标记这些端到端场景通过。

## 每日推荐适配与快照执行边界

实现位置为`backend/music/daily.py`，提供第5.6节的build_user_profile、score_user_cf、calculate_daily、get_daily、refresh_daily，以及serialize_daily。纯计算仍由recommendation.py完成；不复制公式、不接入模拟种子。

- 输入从项目ORM读取：目标用户必须is_active，邻居只取同origin且is_active用户；歌曲仅取created_at严格小于cutoff的现有记录，保留历史歌曲向量用于画像。收藏取当前关系且created_at<cutoff，Behavior只取kind=COMPLETE、origin匹配、occurred_at<cutoff的已持久化事实；PLAY/SKIP不得计入成熟度、热度或过滤。行为服务仍未实现，适配器不声称独立验证收听真实性；合法COMPLETE写入责任不转移到推荐器。
- 媒体资格共用`backend/music/media.py`的`playable_media_path(song:Song)->Path|None`，由SongSerializer与适配器复用。要求active、playback_allowed、checked_at非空、file_path为媒体根内相对路径且实际为文件；路径异常、根目录本身、根外路径及符号链接逃逸均不可播放。该函数不打开文件、不重做解码或许可证审查，checked_at代表受信管理员媒体核验；媒体管理发布流程未完成时，不自动设置任何核验标志。只读stat不授权素材导入或公开传播。
- get_daily/refresh_daily使用timezone-aware统一now，并以`now.astimezone(ZoneInfo("Asia/Shanghai")).date()`归档。事务先锁定User，再锁定当天Snapshot；get_daily已存在时不重算、不改revision/generated_at。缺失时生成revision=1；refresh_daily已存在时原子替换完整items与alpha、revision加1。首次插入使用嵌套事务savepoint，唯一冲突后重读，不吞掉其他IntegrityError。
- 刷新限制以该用户所有日期快照中最新generated_at为准，每次成功生成（包括首次GET创建）后60秒内POST均429；上海午夜不清空限制。首次POST无任何快照时允许且revision=1。新的上海日期首次GET可生成当天快照；GET不受POST限流约束，但该次生成会更新下一次POST允许时刻。拒绝不得写入当天空行或修改任何快照。允许刷新时间=最新generated_at+60秒；next_refresh_at按该值返回，若无其他更新即当前snapshot.generated_at+60秒。Retry-After为剩余秒数向上取整，范围1—60；时钟逆行保守返回60，不覆盖新记录。
- `serialize_daily(*,snapshot:RecommendationSnapshot,user_id:int,now:datetime)->dict`首先验证归属，不属于当前用户返回NOT_FOUND；返回前重读歌曲、当前收藏、近24小时COMPLETE、active标签与歌曲标签关系。下架、许可撤销、文件失效、当前收藏、近24小时完成、证据标签失效/移除、解释不再匹配当前标签名的项全部过滤；不补位，不改存储items/revision/alpha。CF/HOT解释也必须匹配固定模板，HOT不得带标签或邻居数。其余来源的邻居数为生成时的聚合证据，不重算邻居身份。过滤后rank连续从1编号。原items=[]时NO_ELIGIBLE_SONGS；原items非空但投影为空时FILTERED_OUT；有items时null。
- getDaily/refreshDaily仅使用request.now，不接受query参数、客户端日期、用户ID或算法权重。refreshDaily没有requestBody，空体application/json请求才允许。所有每日路由响应（包括错误与CSRF失败）带`Cache-Control: private,no-store`；429额外带Retry-After。HTTP返回完整Daily投影而非模型对象。

本阶段测试仅使用显式内存数据库、合成元数据与模拟文件存在性，验证顺序事务及故障回滚；MySQL并发锁、真实文件/媒体发布、浏览器和推荐质量未验证。不得把SQLite测试写成MySQL迁移/并发通过。

## 管理后台

文件backend/music/admin.py与forms.py。SongAdminForm.clean(self)->dict校验来源、许可、核验时间、文件类型与大小；clean_file_path(self)->str拒绝绝对路径、..分段与媒体根外解析。文件检验不能只靠后缀：WAV头RIFF/WAVE、OGG头OggS、MP3为ID3头或有效MPEG帧头；检验失败VALIDATION_ERROR。文件头有效不代表音频可完整解码，不在论文宣称完整媒体取证。

SongAdmin.save_model(self,request:HttpRequest,obj:Song,form:SongAdminForm,change:bool)->None只允许staff且具有对应模型权限；发布必须人工确认版权，不自动把checked_at设为当前时间。TagAdminForm.clean_name(self)->str返回trim后的1—30字符。UserAdmin不得提供普通用户修改origin的公开入口；模拟账户只能由独立种子命令创建。

## 本机代理与管理后台展示

开发环境DEBUG=True时CSRF_TRUSTED_ORIGINS仅增加http://127.0.0.1:5173；DEBUG=False默认不增加，不使用通配符、不关闭CSRF中间件、不伪造Origin、不改写代理Origin来绕过验证。Vite将/api、/admin、/static转发到127.0.0.1:8000，固定5173且strictPort=True，STATIC_URL=/static/。安全重启后必须重新GET登录页取得当前token，再POST；没有token或来自其他origin的请求仍403。开发可信来源只解决Origin检查，不能替代token及staff身份校验。

保留Django admin，不建设Vue管理后台、不新增依赖。backend/templates/admin的base_site.html、login.html、index.html覆盖原模板，settings.TEMPLATES.DIRS优先加载；本地music/admin.css统一奶油底/深紫/珊瑚色、响应式及深色模式。登录使用原生AdminAuthenticationForm字段、csrf_token和next，不缓存/输出密码；错误真实展示，无默认账号。首页只从Django按权限提供的app_list展示入口，不虚构统计/推荐效果；展示标签→曲库草稿→核验发布的步骤与当前用户近期操作。表单/列表沿用原模板交互、无JS接管提交；中文字段分组、搜索/筛选/分页不改变数据与授权校验。禁止删除媒体等原规则不变。

ADM-M-001至ADM-M-008使用内存SQLite和真实Django Client检查本机代理Origin带token登录成功、无token/非可信来源仍403、API写入同规则、模板资源/脱敏错误/权限隔离与列表表单正常渲染；静态查找和Vite构建验证不等于浏览器视觉验收。重启本机--noreload后端和Vite由用户在其窗口进行，不读取用户密码、不创建真实账号或写入项目库。

### 后台桌面宽度与候选素材边界

首页music-dashboard显式覆盖Django原.dashboard #content的600px固定宽度：width:100%、max-width:1680px、border-box及水平居中；父content和grid子项min-width:0。桌面内容与指南两栏，<=1100px指南移到下方，<=767px单栏；登录页既有双栏不受该规则影响。base_site.html静态样式URL附版本v=20261030-2，避免修复后仍读旧缓存。ADM-M-009/010核对模板引入顺序及宽度选择器/断点规则，不把静态断言视为浏览器布局实测。

用户要求导入D:/AAA素材库/song，本轮仅只读检查该目录直接子文件的格式、大小、SHA256和既有inspect_audio结构结果，不递归读取下载器/IDE缓存，不改动源文件、不转码、不读取歌词全文。清单进入material-audit.json：候选与不支持格式分开，MP3结构通过不等于完整解码，时长未知不以1毫秒占位；许可状态保持UNVERIFIED，不自动猜测歌曲标签/来源URL/授权证据，不连接MySQL或写曲库。系统内复制/发布需先确认使用权及本机安全凭据，不能把“下载过”当播放许可；当前允许用户主动选择文件进行不上传的本地播放。不新增音频依赖或扩大格式支持。

### 本地歌曲资料整理与草稿入库

用户已确认先整理44首MP3及辅助标签。本轮使用Windows Shell System.Title/Music.Artist/Music.AlbumTitle/Media.Duration读取文件元信息；Duration单位100ns，除10000后取整毫秒，空或超1—86400000保留null并禁止入库，不按大小猜时长。标题/歌手缺失仅以第一个ASCII连字符拆文件名；没有连字符时标题用文件名、歌手为空并待核对，不填虚假歌手。输出specs/music/system/local-catalog.json及local-catalog-review.md，记录来源字段、SHA256、字节数、重复内容和metadata_issues；不复制音频、不读取歌词、不安装新库。

music/local_catalog.py的suggest_tags(filename:str)->list[dict]采用显式歌曲候选映射及版本词提示，不执行声学/歌词模型、不联网声称核实曲风。每项含kind/name/confidence/basis，MEDIUM仅常识候选、LOW仅版本词或场景推断，无HIGH；全部needs_review=True。候选不会自动写Tag/SongTag；用户在后台预览后明确勾选accept_tags才应用对应所选歌曲候选。标签来源写入草稿attribution_text，不用于论文真值。无法识别版本的曲目保持空候选。

SongAdmin增加固定local-import/GET预览/POST确认与列表工具入口；只对staff且具有add_song/change_song权限开放，应用标签另需add_tag/add_songtag。只读取固定清单文件，不接受用户指定文件路径；限制清单<=100项，UUID字段不增加；SHA256须64小写hex、.mp3文件名不能含路径分隔符/..、标题/歌手<=120、专辑<=120、时长合法。POST选中hash列表去重、拒绝未知hash；草稿去重标记source_name=LOCAL_DRAFT_SHA256:<hash>，按当前用户行锁序列化相同管理员提交，在transaction.atomic内创建Song和可选Tag/SongTag，既有同hash记录不修改、不重新发布。所有新Song active=False/playback_allowed=False/redistribution_allowed=False/checked_at=None/file_path=''，来源/许可URL和license_name为空，不伪造授权；不复制音频，不把资料入库声称为可播放曲库。至少需要标题、实际时长；歌手缺失项暂不可选，后续核对后再入库。不新增模型/迁移。

导入结果显示新建/已存在数量；失败显示脱敏提示，不落部分关系、不删除既有数据。保留admin CSRF；GET不写数据库，普通用户/越权staff拒绝。通过真实后台用户会话写入专用库，不提取密码、不复用Cookie或绕过浏览器身份。当前Agent无法调用受支持浏览器时只准备入口，由用户在页面确认提交；未实际提交不得称已入库。LC-M-001起覆盖元信息回退/时长、候选性质、非法清单、去重、事务回滚、权限/CSRF及GET不写入，内存测试不冒充MySQL实测。

## 媒体实施边界

文件检测/受控存储位于media.py，表单位于forms.py。`inspect_audio(data:bytes,filename:str)->tuple[str,int|None]`按completion-contract.md检查真实字节，返回MIME及WAV计算时长，MP3/OGG时长为None；失败抛Django ValidationError。大小1—31457280字节；WAV检查RIFF声明长度与实际长度一致、PCM参数与声明帧完整读取；OGG检查首page头、BOS标记、segment表和首page载荷完整；MP3 ID3v2只允许版本2/3/4、同步安全长度且跳过可选v2.4 footer后必须紧接合法MPEG帧头。MP3不作完整帧/解码证明。

SongAdminForm仅保留非持久化preview_confirmed复选框，不默认勾选；active发布要求playback_allowed=True、checked_at非空且不在未来、有效文件以及合法duration_ms(1—86400000)，不再要求rights_confirmed或来源许可输入。MP3/OGG必须preview_confirmed；新上传/替换的MP3/OGG先保存草稿并清空checked_at，再由管理员从受控草稿预览实际收听、填写时长和核验时间后发布；不允许上传同时直接发布。WAV时长差>1000ms拒绝。文件类型与模型mime须一致；草稿无文件可保存，已有文件不上传则保留；file_path绝不从POST赋值。upload不得为空/多文件/超限，验证后才写文件。

保存由SongAdmin.save_model在staff及对应add/change权限校验后进行。`store_audio(*,data:bytes,extension:str)->str`使用uuid4().hex文件名和songs相对目录，最终解析路径必须在MEDIA_ROOT内、独占创建不覆盖；替换旧文件保留，数据库失败记录新孤立文件但不删除。checked_at不自动生成；文件草稿并非获得播放许可。管理员不可直接删除Song/Tag/SongTag，使用下架/停用/编辑，避免破坏历史关联。SongTag权重固定1，禁止同歌重复标签。

SongAdmin添加`<object_id>/preview/`管理员专用媒体预览，要求有效staff并具有view_song或change_song权限；仅提供数据库记录的受控路径，不接受任意路径，允许草稿以完成人工核验。admin只读preview字段展示HTML原生audio controls及说明，无脚本自动确认时长/版权，不下载外部URL。预览不是新增公开API。用户stream仍必须登录、active、playback_allowed、checked_at且受控文件存在。

`resolve_media(*,song_id:int,user_id:int)->tuple[Path,str,int]`先认证有效账户，再歌曲active(404)、许可与核验(403)，最后路径/文件/MIME/大小(503)。`streamSong`不接受query；打开文件后确定字节数，单Range仅接受完整匹配bytes=start-end、bytes=start-或bytes=-suffix且长度<=100，end超文件尾截到末尾，起点超界/反向/零suffix/多段/非法均416、空体、Content-Range: bytes */size。200/206/416均带Accept-Ranges、Content-Length、private,no-store、nosniff，206明确Content-Range；输出只迭代指定区间，不读入整个音频。FileResponse/StreamingHttpResponse负责关闭句柄；打开失败503。HEAD未定义返回405，不自动扩充契约。退出登录后新请求401，不保证撤销浏览器已有缓冲。

本阶段测试全部使用内存合成WAV/MP3/OGG及模拟文件系统，不创建/清理临时媒体、不读取用户素材，不把结构头测试称为浏览器预览或真实授权发布。真实文件版权、完整播放、MySQL迁移/并发与前端计时仍单独验收。

## 前端页面与单播放器执行边界

使用frontend-contract.json全部页面路径和组件、原生hash/fetch、Vue内存状态，不增加依赖。session.ts保存当前用户及通知；启动取CSRF后GET me，匿名401只标记未登录，保护页由路由守卫跳登录。登录后重新获取CSRF，按onboarding_completed进入兴趣/每日页；注销停止在线播放并清空内存身份。客户端网络/非JSON服务错误使用本地NETWORK_ERROR/RESPONSE_ERROR，不冒充后端错误；401清会话、停止在线行为，保护页跳登录，公开页保持可浏览（登录失败AUTH_FAILED不触发）；CSRF_FAILED重取token只提示手工重试，不重发写请求。429读取Retry-After用于刷新倒计时。

页面具备加载/错误重试/空态，提交期间禁用；每日页按返回rank展示并原样显示解释，用song_id查询真实元数据，不造歌曲信息；刷新成功才更新快照，失败保留旧结果。发现/收藏分页，歌单增删改名/成员维护均等待服务器成功，不乐观写入；跨页后过期加载结果不覆盖新页面。所有文字文本渲染，不使用v-html或身份localStorage。

AudioPlayer.vue始终挂载单个audio节点，playback.ts纯控制器依赖注入audio、时钟、UUID、事件发送与对象URL函数，便于无浏览器测试。全局单实例跨页持续；本地File仅objectURL，不上传、不发送行为，切换/离页销毁时撤销URL。本地文件页面离开即停止并撤销，在线播放切页不销毁。PLAY只在实际playing后以零位置/累计上报一次；pause/waiting/seeking/error/ended先冻结performance.now累计，seek不以currentTime差记时。恢复playing沿用会话；切歌先冻结并终止旧会话（>=80%位置及有效累计COMPLETE，否则SKIP），等待旧PLAY结果才允许终止上报，旧请求失败不得补造终止。ended同规则，媒体error不补造COMPLETE。事件队列保存原event_id/载荷，仅NETWORK_ERROR最多3次重试，1/2/4秒；400/401/403/409不改载荷重试，401停止在线采集。自动播放被拒提示点击播放，不报PLAY；本地不影响线上推荐矩阵。播放器与请求逻辑使用Node内置测试器/既有TypeScript编译器测试，不安装浏览器框架；实际音频设备/浏览器解码/MySQL联调另验。

## 实机前跨模块流程回归

## v35 推荐收藏保留与播放器播放模式

范围为前端收藏交互、全局播放器和backend/music/daily.py现有快照读取过滤；不更改接口字段、收藏接口、行为采集协议、数据库或依赖。此节取代此前“快照读取时过滤新增收藏”的规则：读取已有快照保留新增收藏，重新生成时仍按现有引擎排除收藏；下架、媒体无效、证据无效及最近听完过滤不变。

- 每日推荐中收藏歌曲成功后，歌曲继续留在当前推荐列表原位置，仅爱心由空心变为红色实心；不得因收藏动作重新请求每日推荐，也不得从页面移除歌曲。收藏页取消收藏仍允许刷新列表，因为该页面展示的就是收藏集合。
- 全局播放器维护当前在线歌曲队列。播放歌曲时由歌曲列表把当前列表作为队列传入；切换页面播放器继续存在，当前队列不因路由变化清空。单独从歌曲详情播放时队列仅包含该歌曲。
- 播放模式枚举固定为 `list`（列表循环，末首回首首）、`single`（单曲循环，当前歌曲重复）、`order`（顺序播放，末首后停止）、`random`（随机播放，队列大于1时不连续播放同一首）。默认模式为 `list`。模式按钮必须显示当前中文名称，并提供键盘可操作的四项选择。
- 当前列表指当前页面加载的歌曲，不自动请求其他分页；跳过不可播放/非法媒体路径，复制并去重队列，不受页面卸载影响。上一首/下一首在单曲模式下仍切歌，顺序模式边界停止切换；模式会话内保留，不持久化。切账号/退出/停止/本地文件替换清空在线队列；自然结束防止重复结束或旧会话异步完成触发额外切歌。本地文件单曲/列表模式重播自身，顺序/随机结束停止，不上传、不采集行为。
- 音频自然结束后先完成当前歌曲的既有终止行为，再按模式决定下一首；播放器仍只有一个原生audio节点。自动切换失败只提示，不伪造播放行为；本地文件没有在线歌曲队列，结束后不自动切换线上歌曲，仅按上述规则重播自身或停止。
- REC-FAV-001/002、PLAYER-MODE-001/002/003：Node前端测试检查每日模板不绑定收藏后重载、四种模式的队列决策、默认模式和随机不连续；前端全量测试、类型检查和构建必须通过。浏览器实际试听和多曲切换仍需实机验收。

backend/music/test_workflow.py在config.test_settings内存SQLite上执行真实注册/登录/CSRF/API/ORM/推荐服务，不使用force_login替代账户流程，不连接MySQL、不创建磁盘音频、不导入用户素材。测试歌曲与静音WAV均明确标记为合成测试；文件检查/读取由模拟替代，不能称为实际授权发布。

WF-M-001串联注册→登录后token轮换→选择三标签→曲库查询→每日推荐及解释证据→受控Range→PLAY→80%累计COMPLETE与同ID重试→收藏→歌单创建/改名/成员增删→刷新限流/60秒后新revision→退出及匿名拒绝；验证响应Schema和数据库关系。WF-M-002验证跳过兴趣后HOT解释，不伪装内容个性化。WF-M-003验证许可撤回后既有每日快照过滤、元数据不可播放与stream403，恢复许可不由用户API自动完成。WF-M-004验证第二用户不能读写他人歌单、不能复用其他用户事件ID，缺CSRF写入不落库。以上是请求链路回归，不含浏览器DOM/audio事件，也不替代DB-M-001/002/003或完整CT/PT。

## 命令

backend/music/management/commands/evaluate_recommender.py：Command.add_arguments(self,parser:ArgumentParser)->None定义--dataset(required)、--output(required)、--seed(type=int,default=42)；Command.handle(self,*args:object,**options:object)->None。缺输入/非法时间manifest退出2，未知方法拒绝，报告写入显式输出目录且不覆盖已有报告。manifest JSON字段固定source、license_evidence、origin、interactions_path、tags_path、timestamp_timezone、real_timestamps；全部required、拒绝额外键；origin为REAL或SIMULATED、real_timestamps为bool、其余为非空字符串、paths相对manifest目录解析。报告指标按spec.md第5.7节，不读取数据库凭据。

模拟种子命令不纳入本轮批准范围；需要时先补机器字段和签名。HTTP超限、运行错误和非法输入必须回到统一错误码，不自创回退或吞异常。

## 阶段 2：反馈矩阵与标签级 TF-IDF 契约

- 反馈统一映射固定为：收藏=5，播放完成=3；评分5=5、4=4、3=0、1—2=-1。正向矩阵只保留大于0的歌曲分值；1—2分歌曲进入目标用户排除集，3分不进入正向矩阵且不作为内容画像来源。相同用户/歌曲/行为类型取集合或单条关系，不重复累加同类关系。
- `TimedRating(song_id, score, occurred_at)` 只接受整数1—5和有时区时间。截止时间严格为 `< cutoff`；截止后的评分不能进入矩阵、画像、协同分或排除集。收藏和完成播放的既有时间口径不变。
- 内容特征采用标签级 TF-IDF，不引入中文分词：每个有效标签 ID 是一个 token；歌曲文档 token 去重。对 N 首候选/曲库歌曲，`df(t)` 为包含 token 的歌曲数，平滑 `idf(t)=log((1+N)/(1+df(t)))+1`；歌曲 TF 为每个唯一 token 的 `1/len(tokens)`，TF-IDF 向量再做 L2 归一化。无标签歌曲向量为空。
- 用户内容画像由兴趣标签向量和正向反馈歌曲 TF-IDF 向量按既有行为数量混合，兴趣标签使用同一 `idf`；用户画像和歌曲向量使用余弦点积。内容分仍限制在0—1，推荐解释仍只引用实际贡献标签，不虚构标签。
- 纯计算入口：`build_tfidf_vectors(*, songs, active_tags, idf=None) -> tuple[dict[int,float], dict[int,float]]`；`compute_profile(..., tag_idf: dict[int,float] | None = None)`；`positive_matrix` 接受评分反馈。阶段2不接入 Item-CF、场景权重、多样性重排或前端变化。
- TFIDF-001/002/003、FEEDBACK-001/002：覆盖稀有/常见标签权重、无标签/单歌曲/空曲库、截止时间、评分映射、低分排除、来源隔离、推荐解释和旧推荐回归。前端全量测试不因本阶段增加页面行为；后端与文档门禁必须通过。

## 阶段 3：Item-Based 协同过滤独立契约

- `compute_item_cf(*,user_id:int,matrix:dict[int,dict[int,float]],candidate_ids:tuple[int,...],neighbor_limit:int=20)->tuple[dict[int,float],dict[int,int]]`只使用正向反馈矩阵，不读取歌曲标签、文件或数据库。
- 对每首歌曲建立“用户—反馈分值”向量；两首歌曲的相似度采用余弦相似度，按共享正向用户计算，结果裁剪到0—1。目标用户已正向反馈的歌曲不作为 Item-CF 推荐结果，分数固定为0。
- 候选歌曲分数为其与目标用户已正向反馈歌曲的相似度加权和，再除以目标用户正向反馈总分；每个候选最多取相似度最高的20首已反馈歌曲，分数限制在0—1。`neighbor_count`表示实际贡献的已反馈歌曲数量，而不是用户数量。
- 无共享用户、空目标反馈或无候选相似歌曲时返回0分和0个贡献项；输入顺序不影响结果。该阶段只独立提供 Item-CF 纯计算入口，不接入每日推荐、三路融合、场景权重、多样性重排或前端。
- ITEMCF-001/002/003：覆盖相似歌曲召回、反馈权重、已消费歌曲排除、无共享用户、上限截断、输入校验与置换稳定性。

## 阶段 4：三路融合与诊断扩展

- 三路固定为标签内容、User-CF、Item-CF；HOT只作为候选不足或无个性化信号时的补位，不计入三路。
- 推荐项新增`user_cf_score`和`item_cf_score`，保留`cf_score`兼容旧快照；当前管理员诊断显示三路分数、有效权重、来源与解释证据。该阶段不新增迁移、依赖或前端业务行为。
- FUSION-001/002/003：覆盖三路同时有效、缺一路、缺两路、冷启动、旧CF快照兼容、三路解释与每日快照过滤。
## 阶段 1：评分功能契约

- 新增实体 Rating，表名 music_rating；字段为 id、user_id、song_id、score、created_at、updated_at。user_id/song_id 关系级联删除；同一用户同一歌曲唯一一条评分；score 为整数 1—5，数据库检查约束与 API 校验同时生效；song_id+score 建索引。
- API：GET /api/v1/songs/{id}/rating/ 返回 {score: integer|null}；PUT 同路径仅接受 JSON {score: integer}，成功返回 {score: integer}；DELETE 删除当前用户自己的评分并返回204。未登录返回 AUTH_REQUIRED；歌曲不存在或未发布返回 NOT_FOUND；未知字段、非整数、超出1—5返回 VALIDATION_ERROR；接口不暴露其他用户评分。
- Song、歌曲分页、歌单歌曲序列增加 current_rating 字段；已登录用户返回本人评分，未登录返回 null。评分控件可在歌曲列表和详情复用，成功后原位更新，不触发每日推荐重载、不改变播放器队列。
- 评分目前只持久化，不改变现有推荐排序和行为事件；后续阶段统一反馈矩阵时固定映射：1—2 为负向，3 为中性，4—5 为正向。
## v34 前台桌面紧凑布局

范围仅限frontend/src/styles.css与DailyPage.vue展示，不更改API、推荐数量、收藏行为、路由及单播放器生命周期，不修改数据库或新增依赖。

- 宽于760px采用桌面布局：主内容宽min(1440px, calc(100% - 64px))，顶部留白24px，底部为固定播放器预留112px；导航最小高度64px，页面标题32px、下间距20px。1024px以下导航可换行，不强制横向溢出。
- 每日推荐改为无装饰圆环的横向简介栏，内边距20px 24px，标题22px、文案14px，调整兴趣按钮置于右侧且可换行。推荐列表上间距16px，列表标题改为“为你精选”，算法细则收进原生details，默认折叠、键盘可展开；日期、版本、刷新保留。
- 所有内容卡24px内边距、18px圆角；歌曲行上下12px，封面40px，名称保持16px；标签、长歌名和解释自然换行，不固定行高或省略理由。按钮最小高度36px。歌单卡最小高度136px，兴趣标签间距8px；注册/登录卡最大宽480px。
- 固定播放器桌面内边距12px 32px，保留原生audio控件及单实例；不改变播放采集。窄屏<=760px主容器92vw、底部预留220px，简介纵排、歌曲操作换行、播放器两行；按钮触控高度至少44px。长文案与空状态不应横向溢出。
- LAYOUT-001/002/003：使用既有Node测试器与已安装PostCSS解析样式，检查桌面密度、响应式覆盖和每日简介结构；前端全量测试与构建必须通过。静态检查不能冒充浏览器尺寸、首屏歌曲数、真实点击与播放验收；1366×768及1920×1080和窄屏视觉复验另行记录。
# 轻量关注补充（隔离实施）

`getUser(request: Request, id: int) -> Response` 返回UserSummary；`listFollowing(request: Request, id: int) -> Response` 和 `listFollowers(request: Request, id: int) -> Response` 返回UserRelationPage，单page固定20。`followUser(request: Request, id: int) -> Response` 和 `unfollowUser(request: Request, id: int) -> Response` 无body、JSON、CSRF，source取会话，按User PK升序锁双方并重查active，幂等200摘要，自关注400 details=[id]。不自动重试或吞未预期完整性错误。全部users/响应private,no-store。
