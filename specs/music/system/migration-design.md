# 数据模型与首次迁移设计

状态：设计完成，未生成业务迁移、未执行数据库命令。机器定义为[migration-plan.json](migration-plan.json)，业务字段结构仍以[entities.schema.json](entities.schema.json)为唯一来源；计划只补ORM映射与关系，不允许独立改业务字段。

## 首次迁移

目标Django5.2.18、mysqlclient2.3.0。首次设置AUTH_USER_MODEL=music.User，User继承AbstractUser，id显式BigAutoField、username重定义为CharField(max_length=30,unique=True)，保留UserManager。先创建User、Tag、Song、Playlist，再创建关系表、Behavior与RecommendationSnapshot。auth依赖auth.0012_alter_user_first_name_max_length；admin、sessions、contenttypes迁移由固定版本框架提供，不复制其表定义。上线后不允许切换AUTH_USER_MODEL。

除User原生字段外，新增onboarding_completed与origin。原生字段映射：password=CharField(128)、last_login=DateTimeField(null=True,blank=True)、is_superuser=False、first_name/last_name=CharField(150,blank=True)、email=EmailField(254,blank=True)、is_staff=False、is_active=True、date_joined=timezone.now。空白姓名与邮箱保存空字符串；groups与user_permissions使用框架ManyToManyField(blank=True)，关联表由框架固定版本生成。所有API不公开这些权限与密码字段。username规范化为小写后写入，模型validators禁止非ASCII，管理员创建也遵守相同规则。

## 字段与索引

业务字段与列名、空值、字段类、最大长度、唯一关系见机器计划。没有default的新增业务字段必须由服务层提供，不把缺省转换为0或空字符串；时间字段用一次注入的now，checked_at只由管理员审查表单写入。id自动生成，listened_ms无默认。来源字段不能通过公开API修改。

所有FK由ORM生成索引，不额外重复同列索引。复合索引固定为：ix_song_active_id(active,id)、ix_behavior_user_time(user_id,occurred_at)、ix_behavior_session(user_id,listening_session_id)、ix_favorite_user_time(user_id,created_at)、ix_playlist_owner(user_id,id)。唯一名称见计划，event_id通过命名UniqueConstraint生成，不同时设置unique=True造成重复约束。关系on_delete以机器计划为准。

所有字符串先trim；name/title/artist不允许空白，album可为空。URL限定http或https。模型验证不接受bool充当integer；非有限分数与NaN拒绝。分数范围、duration与事件范围由validators及CheckConstraint双层维护；同会话绑定、完成时长、歌单上限、兴趣集合3—5或0属于跨行服务校验，不能宣称单列CheckConstraint足够。

## 安全迁移顺序与验收

当前不生成或执行manage.py migrate，不创建数据库，不请求root凭据。获得专用库和迁移授权后，先验证实际服务版本、字符集、事务隔离及专用用户权限；若复用9.2，记录兼容决定后再运行迁移。目标8.x不因本地9.2存在而自动改变。

获批后的命令设计：先makemigrations --check检查已提交迁移与模型差异，migrate --plan查看计划，经用户批准后对专用空库执行migrate，再运行测试。真实命令只有对应应用与账户存在时才能报告运行；本轮没有这些入口。

验收ID DB-M-001：所有业务表、唯一键、索引、NULL与FK映射符合机器计划。DB-M-002：在专用测试库清空业务表后完整迁移并回滚再迁移，应用表结构一致。DB-M-003：取消或失败事务不留下部分关系。三项均未自动化，期限T02/T04完成前；不针对现有用户数据演练回滚。
