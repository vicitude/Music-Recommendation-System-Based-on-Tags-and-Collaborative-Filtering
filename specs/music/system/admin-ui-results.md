# 管理后台来源修复与界面打磨

日期：2026-10-30。依据：用户报告从127.0.0.1:5173/admin/提交管理员登录，Django拒绝Origin，并要求改善管理后台。

## 根因与修复

浏览器通过Vite5173访问后台，后端仍是8000；默认代理未改写Origin，Django未配置可信开发来源，导致带正确账号及token的请求也可能因Origin检查403。这不是密码错误，也不能通过DEBUG=False修复。settings.py仅在DEBUG=True信任精确http://127.0.0.1:5173，不信任其他端口/localhost/外部域，不关闭中间件、不伪造Origin或增加通配符。

原Vite缺少/static代理，后台资源无法通过5173可靠取得，是页面粗糙的另一配置问题。现增加/static转发、固定5173 strictPort、STATIC_URL=/static/，并同步frontend-contract.json。保留已有/api、/admin及媒体代理，不新增依赖。

## 界面实现

- 本地模板覆盖Django admin登录页、首页和公共外壳；奶油色背景、深紫色品牌区、珊瑚色操作入口。
- 登录页双栏说明/唱片装饰/网站管理员提示、错误展示、原生密码字段与CSRF隐藏字段。装饰通过CSS，不加载外部字体/图片，不缓存密码。
- 首页按真实app_list权限显示歌曲/标签/用户入口、三步上架指南和当前用户近期操作；不填虚假统计数字。
- 列表与表单统一间距、卡片、按钮、焦点、移动布局及显式深色模式样式；歌曲编辑分成歌曲信息、音频预览、来源许可、核验发布四组，中文字段说明，增加歌曲/标签搜索筛选。
- 保留原框架权限、媒体表单校验、预览、发布和禁止删除规则；没有新后台框架、模型改动或数据库迁移。

## 真实验证与限制

新增8项Django Client测试通过：代理来源带token实际密码登录成功、无token拒绝、非可信来源拒绝、API同规则、登录模板转义/错误/无密码回显、首页权限入口隔离、列表和分组表单渲染、静态资源查找及开发静态响应。使用config.test_settings内存SQLite，不读取真实账户或连接MySQL。

新增1项前端配置测试核对5173固定端口及/api /admin /static代理。后端全量201/201、前端47/47通过；Vue类型检查与Vite构建通过，既有大包警告保留；文档门禁及4项自测通过。未安装依赖、写真实数据、导入素材、关闭/重启用户服务或读取密码。

浏览器Node工具入口仍返回unsupported call，未建立受支持会话，未改走其他通道；未执行实际浏览器登录、截图或视觉布局验收。不把模板测试描述成已完成实机后台登录。

复核：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
npm.cmd test --prefix frontend
npm.cmd run build --prefix frontend
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

## 用户启用步骤

后端以--noreload运行，不会自动读取settings更新。在后端窗口Ctrl+C（必要时Ctrl+Break）停止，再运行下面命令，在本机隐藏输入项目数据库密码；不要带--create-admin，管理员和表都已存在，不用重建：

~~~powershell
& 'D:\SOLO\ddd\毕业设计\.venv\Scripts\python.exe' -B 'D:\SOLO\ddd\毕业设计\backend\start_local.py'
~~~

前端通常会自动重载vite.config.ts；若未生效，在前端窗口停止后重新执行npm.cmd run dev --prefix frontend（从项目根目录）。重启可能更换进程随机会话密钥，需要重新登录；这是既有入口规则，不重置密码。重新打开http://127.0.0.1:5173/admin/login/并Ctrl+F5刷新，取得新token后登录，不从旧403页后退直接提交，不混用localhost和127.0.0.1。仍403时只提供脱敏错误，不发送密码或Cookie/token。
