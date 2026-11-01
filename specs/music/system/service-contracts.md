# 服务与管理入口精确定义

状态：开发中。与spec.md第5.6节、implementation-boundaries.md互补；API视图的24个精确名称、参数、请求Schema和响应状态见[api-bindings.json](api-bindings.json)。24个操作及媒体管理、行为/推荐服务已实现；真实媒体、MySQL、前端与完整契约未验收，最新见[媒体验证](media-results.md)。

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
- get_daily与refresh_daily签名以spec.md为准，持久化Snapshot；投影由serialize_daily(*,snapshot:RecommendationSnapshot,user_id:int,now:datetime)->dict生成，过滤并重新编号，不写回revision。
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
- `RecommendationResult(items:list[RecommendationItem],alpha_target:float,alpha_effective:float|None,empty_reason:str|None)`为内部结果，不含快照日期/版本/刷新时间；不得直接当作Daily API响应。RecommendationItem结构完全复用实体Schema。空候选empty_reason=NO_ELIGIBLE_SONGS，否则null；HOT项仍属于非空候选。
- `recommend(*,user_id:int,now:datetime,songs:tuple[SongFeatures,...],users:tuple[UserSignals,...],active_tags:dict[int,str],limit:int=20)->RecommendationResult`；limit为1—20整数，bool不算整数。歌曲与用户ID唯一，ID为正整数；目标用户必须存在；无效纯计算输入抛ValueError，不自创公开错误码。
- `content_weight(*,positive_song_count:int)->float`采用第5.4节公式，拒绝负数、非整数与bool。`positive_matrix(*,users:tuple[UserSignals,...],cutoff:datetime,origin:str)->dict[int,dict[int,float]]`仅接纳同来源且occurred_at严格小于cutoff的当前收藏和合法完成事实；按歌曲去重，收藏5、完成3，合计不超过8。
- `compute_profile(*,interest_ids:tuple[int,...],positive_scores:dict[int,float],song_vectors:dict[int,dict[int,float]])->dict[int,float]`实现第5.3节画像。历史正反馈歌曲不在歌曲特征集中时，仅其内容向量为零，不删除其CF维度或成熟度贡献。
- `compute_cf(*,user_id:int,matrix:dict[int,dict[int,float]],candidate_ids:tuple[int,...],neighbor_limit:int=20)->tuple[dict[int,float],dict[int,int]]`返回候选原始协同分数及实际贡献邻居数量；共同歌曲至少2，按相似度降序/user_id升序取最多20人，每首歌分母只含对该歌正向贡献的邻居。
- `fuse_candidates(*,candidate_ids:tuple[int,...],content_scores:dict[int,float],cf_scores:dict[int,float],evidence_tags:dict[int,tuple[int,...]],neighbor_counts:dict[int,int],popularity:dict[int,int],active_tags:dict[int,str],positive_song_count:int,limit:int=20)->RecommendationResult`只在完整候选集上分别除以最大值归一化，使用未舍入值排序；出参三项歌曲得分round(...,6)。该入口用于数学oracle和引擎复用，不是公开API。热门补位不改变个性化得分和alpha。

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

SongAdminForm增加非持久化rights_confirmed和preview_confirmed复选框，均不默认勾选；active发布必须明确rights_confirmed、许可/来源非空、playback_allowed=True、checked_at非空且不在未来、有效文件以及合法duration_ms(1—86400000)。MP3/OGG必须preview_confirmed；新上传/替换的MP3/OGG先保存草稿并清空checked_at，再由管理员从受控草稿预览实际收听、填写时长和核验时间后发布；不允许上传同时直接发布。WAV时长差>1000ms拒绝。文件类型与模型mime须一致；草稿无文件可保存，已有文件不上传则保留；file_path绝不从POST赋值。upload不得为空/多文件/超限，验证后才写文件。

保存由SongAdmin.save_model在staff及对应add/change权限校验后进行。`store_audio(*,data:bytes,extension:str)->str`使用uuid4().hex文件名和songs相对目录，最终解析路径必须在MEDIA_ROOT内、独占创建不覆盖；替换旧文件保留，数据库失败记录新孤立文件但不删除。checked_at不自动生成；文件草稿并非获得播放许可。管理员不可直接删除Song/Tag/SongTag，使用下架/停用/编辑，避免破坏历史关联。SongTag权重固定1，禁止同歌重复标签。

SongAdmin添加`<object_id>/preview/`管理员专用媒体预览，要求有效staff并具有view_song或change_song权限；仅提供数据库记录的受控路径，不接受任意路径，允许草稿以完成人工核验。admin只读preview字段展示HTML原生audio controls及说明，无脚本自动确认时长/版权，不下载外部URL。预览不是新增公开API。用户stream仍必须登录、active、playback_allowed、checked_at且受控文件存在。

`resolve_media(*,song_id:int,user_id:int)->tuple[Path,str,int]`先认证有效账户，再歌曲active(404)、许可与核验(403)，最后路径/文件/MIME/大小(503)。`streamSong`不接受query；打开文件后确定字节数，单Range仅接受完整匹配bytes=start-end、bytes=start-或bytes=-suffix且长度<=100，end超文件尾截到末尾，起点超界/反向/零suffix/多段/非法均416、空体、Content-Range: bytes */size。200/206/416均带Accept-Ranges、Content-Length、private,no-store、nosniff，206明确Content-Range；输出只迭代指定区间，不读入整个音频。FileResponse/StreamingHttpResponse负责关闭句柄；打开失败503。HEAD未定义返回405，不自动扩充契约。退出登录后新请求401，不保证撤销浏览器已有缓冲。

本阶段测试全部使用内存合成WAV/MP3/OGG及模拟文件系统，不创建/清理临时媒体、不读取用户素材，不把结构头测试称为浏览器预览或真实授权发布。真实文件版权、完整播放、MySQL迁移/并发与前端计时仍单独验收。

## 前端页面与单播放器执行边界

使用frontend-contract.json全部页面路径和组件、原生hash/fetch、Vue内存状态，不增加依赖。session.ts保存当前用户及通知；启动取CSRF后GET me，匿名401只标记未登录，保护页由路由守卫跳登录。登录后重新获取CSRF，按onboarding_completed进入兴趣/每日页；注销停止在线播放并清空内存身份。客户端网络/非JSON服务错误使用本地NETWORK_ERROR/RESPONSE_ERROR，不冒充后端错误；401清会话、停止在线行为，保护页跳登录，公开页保持可浏览（登录失败AUTH_FAILED不触发）；CSRF_FAILED重取token只提示手工重试，不重发写请求。429读取Retry-After用于刷新倒计时。

页面具备加载/错误重试/空态，提交期间禁用；每日页按返回rank展示并原样显示解释，用song_id查询真实元数据，不造歌曲信息；刷新成功才更新快照，失败保留旧结果。发现/收藏分页，歌单增删改名/成员维护均等待服务器成功，不乐观写入；跨页后过期加载结果不覆盖新页面。所有文字文本渲染，不使用v-html或身份localStorage。

AudioPlayer.vue始终挂载单个audio节点，playback.ts纯控制器依赖注入audio、时钟、UUID、事件发送与对象URL函数，便于无浏览器测试。全局单实例跨页持续；本地File仅objectURL，不上传、不发送行为，切换/离页销毁时撤销URL。本地文件页面离开即停止并撤销，在线播放切页不销毁。PLAY只在实际playing后以零位置/累计上报一次；pause/waiting/seeking/error/ended先冻结performance.now累计，seek不以currentTime差记时。恢复playing沿用会话；切歌先冻结并终止旧会话（>=80%位置及有效累计COMPLETE，否则SKIP），等待旧PLAY结果才允许终止上报，旧请求失败不得补造终止。ended同规则，媒体error不补造COMPLETE。事件队列保存原event_id/载荷，仅NETWORK_ERROR最多3次重试，1/2/4秒；400/401/403/409不改载荷重试，401停止在线采集。自动播放被拒提示点击播放，不报PLAY；本地不影响线上推荐矩阵。播放器与请求逻辑使用Node内置测试器/既有TypeScript编译器测试，不安装浏览器框架；实际音频设备/浏览器解码/MySQL联调另验。

## 实机前跨模块流程回归

backend/music/test_workflow.py在config.test_settings内存SQLite上执行真实注册/登录/CSRF/API/ORM/推荐服务，不使用force_login替代账户流程，不连接MySQL、不创建磁盘音频、不导入用户素材。测试歌曲与静音WAV均明确标记为合成测试；文件检查/读取由模拟替代，不能称为实际授权发布。

WF-M-001串联注册→登录后token轮换→选择三标签→曲库查询→每日推荐及解释证据→受控Range→PLAY→80%累计COMPLETE与同ID重试→收藏→歌单创建/改名/成员增删→刷新限流/60秒后新revision→退出及匿名拒绝；验证响应Schema和数据库关系。WF-M-002验证跳过兴趣后HOT解释，不伪装内容个性化。WF-M-003验证许可撤回后既有每日快照过滤、元数据不可播放与stream403，恢复许可不由用户API自动完成。WF-M-004验证第二用户不能读写他人歌单、不能复用其他用户事件ID，缺CSRF写入不落库。以上是请求链路回归，不含浏览器DOM/audio事件，也不替代DB-M-001/002/003或完整CT/PT。

## 命令

backend/music/management/commands/evaluate_recommender.py：Command.add_arguments(self,parser:ArgumentParser)->None定义--dataset(required)、--output(required)、--seed(type=int,default=42)；Command.handle(self,*args:object,**options:object)->None。缺输入/非法时间manifest退出2，未知方法拒绝，报告写入显式输出目录且不覆盖已有报告。manifest JSON字段固定source、license_evidence、origin、interactions_path、tags_path、timestamp_timezone、real_timestamps；全部required、拒绝额外键；origin为REAL或SIMULATED、real_timestamps为bool、其余为非空字符串、paths相对manifest目录解析。报告指标按spec.md第5.7节，不读取数据库凭据。

模拟种子命令不纳入本轮批准范围；需要时先补机器字段和签名。HTTP超限、运行错误和非法输入必须回到统一错误码，不自创回退或吞异常。
