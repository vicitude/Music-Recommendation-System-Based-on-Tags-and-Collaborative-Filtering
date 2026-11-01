# 跨模块流程回归与实机前置核验

日期：2026-10-30。关联实现：backend/music/test_workflow.py；后续操作：[本机启动与实机验收操作单](live-acceptance.md)。

## 核验结果

本机MySQL92运行且3306监听，8000/5173未观察到监听；当前执行进程未配置MYSQL_*/DJANGO_*环境变量。只读取项目模板和服务/端口状态，没有连接数据库、读取凭据或创建账号。backend/.env.example不会被settings.py自动加载，不能把模板存在当成连接已配置。

现有素材路径不等于系统内在线播放许可，未扫描、复制、转换或导入用户音频；专用库和账户用途、迁移执行及合法媒体发布仍待明确授权。实机操作单给出配置/迁移/启动顺序、许可准入、LIVE-01至LIVE-10验收与停止条件，未执行其中的数据库/服务命令。

## 新增自动化结果

| 编号 | 请求链路 | 结果 |
|---|---|---|
| WF-M-001 | 真实注册/密码登录/CSRF轮换、兴趣、曲库、推荐解释、合成WAV受控Range、PLAY/COMPLETE/同ID重试、收藏、歌单增删改及成员、刷新限流/新revision、退出和匿名拒绝 | 通过 |
| WF-M-002 | 跳过兴趣后使用HOT和明确热门解释，不冒充标签个性化 | 通过 |
| WF-M-003 | 许可撤回后既有快照过滤、元数据不可播放、stream403 | 通过 |
| WF-M-004 | 第二账户无法读写私有歌单，跨用户事件ID冲突409，缺CSRF写入403且无新关系 | 通过 |

这些测试走真实Django会话/API/ORM/推荐实现，不使用force_login代替账户链路；数据库是config.test_settings内存SQLite。静音WAV在内存生成，文件检查/打开由模拟替代，未保存磁盘媒体。Schema核验覆盖这些流程所用响应，不代表CT-M-001全部分支穷举。时钟可控且无真实等待，不是网络并发或浏览器音频事件验证。

首次执行WF-M-004时测试断言误用不存在的IDEMPOTENCY_CONFLICT；按现有error-catalog.json修正为EVENT_CONFLICT后通过，没有变更后端错误契约或降低状态码断言。

## 运行证据

- 工作流定向4/4通过。
- 后端全量181/181通过（原177项+本轮4项）。
- 前端离线46/46通过；前端源码和依赖本轮未修改，未重复构建，最近构建结果见frontend-results.md。
- 离线文档门禁通过，4项门禁自测通过。
- 未连接MySQL、运行迁移/回滚、创建持久数据、启动常驻服务、安装依赖、删除文件或执行Git操作。

复核命令：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music.test_workflow --settings=config.test_settings --verbosity=2
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
npm.cmd test --prefix frontend
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

## 尚未验收

浏览器真实操作/音频解码/墙钟累计、实际磁盘媒体、授权发布、MySQL连接/迁移/并发、完整CT/PT、性能和推荐效果实验均未验收。单用户注册链路和HOT/CONTENT解释通过不能推导User-CF在真实用户上的效果提升。下一步需集中确认专用开发库操作范围和可发布音频来源；没有许可时先验非播放页面，不生成虚假版权证据或模拟演示数据混入真实库。
