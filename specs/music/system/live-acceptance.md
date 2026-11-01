# 本机启动与实机验收操作单

日期：2026-10-30。状态：用户已完成专用库初始迁移、管理员创建与前后端启动。代理后台Origin403已修复并打磨界面，需重启后端及刷新登录页实机确认，见admin-ui-results.md。下文前置检查保留历史准备信息；素材许可、完整数据库/浏览器验收仍未完成。适用范围：仅本机127.0.0.1，不公开部署，不访问其他业务库。

## 1. 已核对的条件

- MySQL92服务运行，3306监听；这不证明账户权限、连接兼容或迁移通过。
- 本次未观察到8000/5173监听，未启动常驻服务。
- 当前执行进程没有MYSQL_*/DJANGO_*数据库/服务配置环境变量。未查找或读取用户凭据。
- backend/.env.example是模板；当前settings.py只读进程环境，不自动加载.env。复制模板本身不会配置数据库，不新增dotenv依赖。
- 现有前后端依赖已装；无需重新安装。config.test_settings使用内存SQLite及测试密码哈希，仅供测试，不能作为持久演示库或正式启动配置。
- 用户提供的song/midi路径不等于获得在线播放/发布许可；本轮未重新扫描、复制或导入。

## 2. 一次确认的实施边界

既定本机开发范围如下；本轮仅推进已批准的专用开发库和后端，缺少凭据不得试探：

1. 复用MySQL9.2，仅使用专用开发库music_recommender_dev及专用账户music_recommender_app。库已存在且用途/数据不明确时立即停下，不覆盖、不清空；不探测root密码、不重置账户、不读取其他业务库。
2. 连接后核对版本/utf8mb4/事务及权限，查看迁移计划；确认是项目专用空库且兼容后执行既有迁移，不改MySQL全局配置、不做回滚/删表。
3. 通过交互方式创建项目管理员，密码由用户在本机输入；不写入文档/源码/日志，不默认预置账号。
4. 启动Django和Vite，仅绑定127.0.0.1:8000/5173。后台启动遵循隐藏窗口；失败保留明确原因，不改端口去访问未知服务。
5. 媒体仅导入另行确认的有权使用音频。若无法提供许可，媒体发布和实际播放保持待验，不能用下载路径或“仅毕业设计”代替授权。

music_recommender_test的创建、迁移回滚、并发与Django测试库创建/销毁是单独阶段，不包含在上述开发库授权中。不得直接对配置默认值执行MySQL测试，避免自动创建或销毁未确认的test_*库。

## 3. 本地配置与启动顺序（授权后执行）

### 安全交互入口

backend/start_local.py使用现有项目解释器运行，固定config.settings、127.0.0.1:3306、music_recommender_dev、music_recommender_app，不接受其他主机/库/账户。支持--check-only（连接及专用库只读核验后退出）和--create-admin（迁移完成后进入Django交互创建管理员），不能同时使用。没有MYSQL_PASSWORD时必须在交互终端通过getpass隐藏输入，非交互调用直接退出2，不试空密码；不读取.env/凭据存储，不保存或输出密码，不创建数据库/账户，不安装依赖。

连接后核对实际库名、CURRENT_USER账户、MySQL9.2版本、utf8mb4、事务隔离；数据库须为空，或只含当前项目模型表及django_migrations且存在music.0001_initial迁移记录。非项目表、非InnoDB表、未知用途/半完成迁移均停止，不覆盖/清空。现有已迁移库的对象名称及迁移记录只是安全入口检查，不代替完整结构DB-M-001验收。查看迁移计划后须在本机输入完整确认短语APPLY music_recommender_dev才执行migrate；失败停下，不自动回滚。迁移完成可交互创建管理员，最后仅启动127.0.0.1:8000、关闭重载。端口占用时停止，不杀其他进程、不换未知端口。Ctrl+C退出服务器，不删数据。

未配置DJANGO_SECRET_KEY时生成仅当前启动进程存在的随机值，不落盘，重启后登录会话可能失效；需要稳定会话由用户在本机进程环境安全配置稳定随机值。日志只输出脱敏错误类别，不回显数据库异常中的账户/连接细节。数据库版本/字符集检查失败不自动改全局配置。

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/start_local.py --check-only
& '.\.venv\Scripts\python.exe' -B backend/start_local.py --create-admin
~~~

第二条供用户在本机交互终端执行。Agent当前没有专用数据库密码，不把入口准备完成当作服务启动成功。管理员已存在时可不加--create-admin；数据库不存在/账户不可用时由数据库管理员先准备，不在本入口用root创建。启动器本身使用伪数据库游标和模拟命令测试，不触达MySQL。

### 手动配置与原生命令

环境变量须在启动后端的同一进程会话配置：MYSQL_HOST=127.0.0.1、MYSQL_PORT=3306、MYSQL_DATABASE=music_recommender_dev、MYSQL_USER=music_recommender_app、MYSQL_PASSWORD为专用密码；DJANGO_SECRET_KEY为本机生成的随机值；DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost。密码由用户在本机安全输入，不贴入聊天，也不使用示例change-me。MEDIA_ROOT使用项目内专用绝对路径，不指向原素材库，防止把源文件当成系统存储。

数据库管理员先准备专用空库和仅项目所需权限的账户；Agent不在缺少授权/凭据时自行创建账户或试密码。库或账户存在时核对用途，遇到冲突停止。开发账户不获得全局权限，不以root运行应用。

以下是顺序模板，本轮没有执行连接/迁移/启动命令：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py check
& '.\.venv\Scripts\python.exe' -B backend/manage.py migrate --plan
& '.\.venv\Scripts\python.exe' -B backend/manage.py migrate
& '.\.venv\Scripts\python.exe' -B backend/manage.py createsuperuser
& '.\.venv\Scripts\python.exe' -B backend/manage.py runserver 127.0.0.1:8000 --noreload
~~~

后端运行后，在另一个本机终端从项目根目录启动前端：

~~~powershell
npm.cmd run dev --prefix frontend
~~~

主站http://127.0.0.1:5173/#/discover，管理入口优先http://127.0.0.1:5173/admin/，由Vite代理到后端，避免登录/CSRF混用localhost与127.0.0.1。不开放0.0.0.0，不改CSRF检查。管理员先创建三类标签，再维护有权使用歌曲的草稿。关闭服务不会删除开发库或媒体；本轮不自动清理任何数据。

## 4. 音频准入

每首记录来源名称/URL、许可名称/条款URL、署名、是否允许应用内播放、是否允许再分发、核验时间及证据存放位置。不伪造URL、不把来源链接当许可本身。非公开自有作品应先明确符合现有表单的合法证据记录方式，再发布，不为凑演示绕过表单。

仅WAV/MP3/OGG、每首不超过30MiB。填写实测duration_ms、匹配MIME。MP3/OGG必须先inactive草稿保存，从管理页实际预览至少5秒（短曲完整播放），确认实际时长与解码后再人工核验发布。WAV结构校验也不是版权或浏览器播放证明。MIDI不能直接作为当前播放器音频，不擅自转换/批量导入。

准备至少三首合法可播放曲目及三个标签即可验收主要页面；没有足量候选时如实显示空态，不能伪造协同邻居或推荐理由。单用户的功能演示不能证明协同质量或自适应融合收益。

## 5. 浏览器逐项验收

| 顺序 | 操作 | 通过条件与记录 |
|---|---|---|
| LIVE-01 | 注册普通用户、登录、退出、重新登录 | 密码不回显；会话正常；私有页匿名跳登录；刷新仍识别账户 |
| LIVE-02 | 新用户选择3个兴趣标签；另一个用户跳过 | 选择持久化；跳过用户不得被描述为已有标签个性化 |
| LIVE-03 | 发现页搜索/标签/分页，打开详情 | 元数据与后台一致；不可播放项禁用；来源链接仅http/https |
| LIVE-04 | 每日推荐与手动刷新 | 理由/顺序与响应一致；60秒内不能刷新；空库/过滤空态有说明 |
| LIVE-05 | 播放，切页，再切歌 | 始终只有一个audio；在线跨页不中断；每会话PLAY只一次；旧会话先终止 |
| LIVE-06 | 播放→暂停→恢复；拖到结尾 | 暂停/缓冲/拖动不累计；仅位置到末尾不能伪造COMPLETE；后端effective_ms复核 |
| LIVE-07 | 完整收听，收藏/取消，创建/改名/成员增删歌单 | 页面等服务器成功后更新；完成/收藏项按规则过滤；删除须二次确认 |
| LIVE-08 | 第二账户尝试第一账户歌单 | 读写均404；收藏、兴趣、推荐不串账号 |
| LIVE-09 | 打开用户主动选择的本地音频、切页 | 无上传/behavior请求；只播放本地；离页停止并撤销objectURL |
| LIVE-10 | 可控断网/恢复、会话失效、许可撤回 | 同event_id有限重试；非网络错误不重发；401停止在线采集；下架/撤权不再播放推荐 |

记录实际数据库版本、浏览器版本、歌曲许可引用、操作时间、失败原因及脱敏请求/响应，不保存密码、Cookie、token或个人敏感信息。截图仅在工具可用且获允许时记录；工具不可用则保持未执行，不替换成测试断言或其他通道绕过。LIVE全部完成后仍不能把性能/完整CT/PT或真实实验标为通过。

## 6. 无数据库的可复核验证

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music.test_workflow --settings=config.test_settings --verbosity=2
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
npm.cmd test --prefix frontend
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

这里的数据库是内存SQLite测试库，不连接MySQL。合成静音音频仅用于测试进程，磁盘媒体打开由模拟替代；既不写入用户曲库，也不证明真实浏览器播放。
