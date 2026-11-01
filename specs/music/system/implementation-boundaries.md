# 实施边界补充：SPEC-MUSIC-001

状态：提议补充；规则纳入spec.md第4至第6部分。环境观察见environment.md。本文件不给予实施或安装授权。

## 1. 空值、检索、排序与失效对象

- q缺省为空字符串，trim后为空不加关键词条件；非空时对title与artist做大小写不敏感包含匹配，二者OR；tag_id用AND条件且必须是active标签，否则400 VALIDATION_ERROR。
- page缺省1，page_size缺省20、范围1—100；未知query参数、重复单值query参数均400。总数0且page=1返回200空results；非空总数下page超过ceil(count/page_size)或总数0且page>1均404 NOT_FOUND；小于1或非整数为400。
- songs按song_id升序，只展示active歌曲；favorites按created_at降序、id降序分页；tags按kind的STYLE/MOOD/SCENE次序及id升序，仅返回active标签；interests响应tag_ids升序并过滤停用标签，不自动把onboarding_completed改回false。
- playlist detail的songs按PlaylistSong.created_at、id升序，隐藏下架歌曲但不删除关联，也不自动补位。收藏列表隐藏下架歌曲。停用标签仍保留历史关系，在画像与公共响应中排除。
- playable=true当且仅当active、playback_allowed、checked_at非空、媒体文件存在且类型已校验；否则false且stream_url=null；playable=true时stream_url固定为/api/v1/songs/{id}/stream/。查元数据不要求已登录，实际stream要求登录。
- checked_at仅许可校验尚未完成时为null；alpha_effective只在两路均无正候选时为null。Snapshot响应empty_reason有items时为null、原始计算无可用候选时为NO_ELIGIBLE_SONGS、已有快照在返回前过滤为空时为FILTERED_OUT。
- Snapshot存储的items rank是生成时排序，返回过滤后重新从1连续编号，不改库中revision。标签停用或改名后，现有解释失去可验证证据的推荐项直接过滤；刷新后重新生成。不得返回与标签名已不一致的旧解释。

## 2. 暂停、拖动与播放事件

为区分暂停与有效收听，在Behavior、BehaviorRequest中增加必填listened_ms，范围0—86400000整数，无默认；纳入event_id载荷一致性比较。

- PLAY必须position_ms=0且listened_ms=0。流资源实际触发playing后发送；请求失败不假装已建会话。
- listened_ms为客户端在playing且非paused、非seeking、非waiting时累计的单调时钟毫秒，取floor；暂停/等待/拖动不累加，播放结束或主动切歌时冻结该值。不能用currentTime差值计算，跳转不增加已听时长。
- effective_ms=min(listened_ms,服务器从PLAY接收起算的elapsed_ms,duration_ms)。COMPLETE还要求position_ms>=ceil(0.8*duration_ms)且effective_ms>=ceil(0.8*duration_ms)；SKIP的position_ms允许0—duration_ms，终止当前会话。
- 暂停与继续不新增PLAY、不更换listening_session_id；重新开始一轮播放或切换歌曲创建新UUID。一个用户同一listening_session_id只能绑定一首歌。
- 客户端不发送周期心跳，服务器无法独立证实客户端listened_ms；恶意伪造仍可能发生，研究报告必须说明自报事件的局限，不宣称全程可信或反作弊完备。
- 页面关闭丢失的终止事件不补造；终止事件重试复用event_id和原载荷，401停止上传，400/409提示且不自动改载荷，网络失败最多3次重试、间隔1/2/4秒，失败后不计有效播放。

例：歌曲100000ms，暂停10分钟，客户端实际只播放1000ms，则effective_ms=1000，COMPLETE拒绝；即使position_ms因拖动达到90000也不改变结论。

## 3. 写操作校验顺序与并发

1. 中间层先生成request_id，写请求先验证CSRF，再验证登录；因此未登录且CSRF也缺失时固定403 CSRF_FAILED，带合法CSRF但未登录时401 AUTH_REQUIRED。
2. 校验JSON结构、未知字段、类型与枚举，失败400；再查访问对象及权限。歌单他人资源一律404，不先返回是否超限。
3. 行为在格式验证后先查event_id：自有完全一致返回200，即使歌曲随后下架也不重计；不同载荷或其他用户占用返回409 EVENT_CONFLICT。新事件再检查歌曲active、会话绑定与状态，最后检查position/listened上界和完成门槛。
4. 同会话换song_id为INVALID_TRANSITION。已终止时相同事件重传仍优先幂等，其他新终止事件为INVALID_TRANSITION（包括同kind不同event_id）；未终止时相同(user_id,listening_session_id,kind)但不同event_id为EVENT_CONFLICT。已终止后新PLAY也为EVENT_CONFLICT，重新播放必须新会话；细节见service-contracts.md行为边界。
5. 并发写入先锁定目标User行，再锁定Playlist或当日Snapshot行，所有入口使用同一顺序。首次snapshot创建也先锁User，避免不存在行无法加锁。数据库唯一约束是最后保障，不能把唯一冲突暴露为500。
6. create_playlist、add_playlist_song的上限在加锁后计数；幂等关系已存在优先204，不因当前容量已满拒绝重试。DELETE自有关系不存在204；DELETE不存在的playlist资源404。
7. 事务Isolation使用READ COMMITTED、字符集utf8mb4、应用时区UTC；连接凭据只从环境读取，不把真实值写入规格、日志或示例。数据库版本兼容尚未通过，不能执行迁移。
8. stream先校验会话、歌曲active及许可，再检查文件和Range；下架404、无播放权403、已获许可但文件丢失503。Range语法错误、多段和不可满足均416。用户退出登录后即不再获得新的媒体响应，不承诺能撤回浏览器已缓冲内容。

## 4. 迁移与服务的准备清单

本节确定补充业务字段，不能取代经实际Django版本生成和验证的完整迁移。

- 新增Behavior.listened_ms为非空INT，无数据库默认；旧Schema无存量业务数据，不需要伪造回填脚本。
- 唯一约束名称：uq_tag_kind_name、uq_song_tag、uq_user_tag、uq_favorite、uq_playlist_song、uq_behavior_event、uq_behavior_session_kind、uq_snapshot_user_day。
- 查询索引名称：ix_song_active_id(active,id)、ix_behavior_user_time(user_id,occurred_at)、ix_behavior_session(user_id,listening_session_id)、ix_favorite_user_time(user_id,created_at)、ix_playlist_owner(user_id,id)。索引允许Django自动创建外键索引，禁止重复同列同序手工索引。
- PLAY载荷与行为唯一关系不引入新的持久化实体；在User锁保护内检查该会话所有已记录事件。
- 补充服务入口签名：set_interests(*,user_id:int,tag_ids:list[int])->list[int]；set_favorite(*,user_id:int,song_id:int,present:bool)->None；create_playlist(*,user_id:int,name:str,now:datetime)->Playlist；rename_playlist(*,user_id:int,playlist_id:int,name:str)->Playlist；delete_playlist(*,user_id:int,playlist_id:int)->None；set_playlist_song(*,user_id:int,playlist_id:int,song_id:int,present:bool)->None。所有时间从外层统一now注入推荐与行为服务，不混用多个时钟。
- API处理入口以OpenAPI operationId为名称，字段投影以OpenAPI response为准，不直接返回数据库对象。框架视图方法与完整管理后台表单签名在精确框架版本锁定后才能固定，本轮不假称已完成。

## 5. 验证执行边界

只读环境检查可以运行现有解释器标准库；契约静态检查不安装验证库。当前可检查JSON解析、引用、字段一致、示例、参数与测试编号；不能仅凭这些检查声称OpenAPI或Gherkin完全合规。

实施批准后拟使用Django测试承载TC、CT、PT与NF编号；属性输入以固定seed标准库生成，不先新增PBT库。Gherkin步骤绑定、OpenAPI完整校验与CI真实入口仍须另行明确工具和批准其依赖，不能用不存在的manage.py或CI命令冒充已通过门禁。项目未初始化Git，变更日志保持空表。
