# 项目隔离依赖安装记录

本文保存2026-10-29安装阶段的历史事实，不代表最新业务进度。后续基础API与27项内存测试结果见[实施验证](implementation-results.md)；MySQL连接和迁移仍未验证。

日期：2026-10-29。用户批准使用现有Python3.13.17创建项目隔离环境、安装项目内依赖，并优先验证MySQL9.2；不授权建库、改数据库配置或操作已有数据。

## 当前结果：依赖安装完成，业务实施门槛仍未通过

本轮用户开启网络代理后重新使用官方PyPI下载。下表替代此前“部分完成”的状态；前端未重复安装。

| 项目 | 结果与证据 |
|---|---|
| Python隔离环境 | .venv由D:/Python313/python.exe创建，版本3.13.17；未继承全局site-packages，未修改PATH |
| Python已安装 | Django5.2.18、DRF3.16.1、NumPy2.5.4、SciPy1.18.1、mysqlclient2.3.0、jsonschema4.26.0、openapi-spec-validator0.8.5、behave1.3.3及传递依赖全部安装，pip26.2.2 |
| Python缺项 | 本次requirements-dev.in中的依赖已满足；未增加范围外软件 |
| Python下载 | 重试后完成官方源下载，采用预编译wheel，未调用本机编译器；安装进程已结束 |
| 前端 | Vue3.5.44、Element Plus2.14.7、Vite7.3.7、TypeScript5.9.3、vue-tsc3.3.13、plugin-vue6.0.10已安装到frontend/node_modules |
| 前端锁 | frontend/package-lock.json已生成，记录解析版本与integrity；package.json保留兼容范围，重装使用npm ci |
| 安装脚本 | npm install使用--ignore-scripts，不执行依赖生命周期脚本；没有安全审计（--no-audit），不能宣称无漏洞 |
| 前端验证 | npm ls --depth=0无缺失；Vue与Vite可导入；tsc --version与vite --version成功；未建立应用，没有执行应用build或浏览器测试 |
| Python验证 | pip check、8个主依赖导入、NumPy/SciPy稀疏矩阵算例、OpenAPI3.1完整文档校验、11份实体Schema元模式校验、2份feature文件语法解析均通过；没有运行场景步骤或业务接口 |
| 数据库 | Django MySQL后端与mysqlclient可加载；读取已装Django源码发现MySQL最低版本门槛为8.0.11，不能仅凭9.2高于该值断言完全兼容。一次探针误读惰性属性触发ensure_connection代码路径，但在缺CONN_HEALTH_CHECKS时即KeyError终止，尚未进入驱动连接；没有数据库认证、SQL、建库或迁移。随后仅用inspect读取源码，不继续访问惰性属性 |

## 锁定状态

已生成根目录requirements.lock，记录本次Windows x64 / Python3.13.17全部已装包的精确版本（含pip），不是带哈希的跨平台可复现锁；尚未在第二个干净环境验证重装。requirements.in与requirements-dev.in保留候选范围。

frontend/package-lock.json为实际安装产物；根目录.gitignore排除.venv、node_modules、缓存、媒体、密钥及日志。当前无Git初始化和业务代码。

## 可复核命令

~~~powershell
& '.\.venv\Scripts\python.exe' -I -B -m pip list --disable-pip-version-check
& '.\.venv\Scripts\python.exe' -I -B -m pip check
npm.cmd ls --depth=0 --prefix frontend --no-audit --no-fund
node frontend/node_modules/typescript/bin/tsc --version
node frontend/node_modules/vite/bin/vite.js --version
~~~

## 后续边界

本次批准范围的安装已完成。新增工具、全局安装、解释器升级或数据库变更仍需另行确认；数据库账户及操作范围授权仍缺失。安装检查结束时无本轮安装器运行。

后台安装尝试被执行策略拒绝，未绕过，也未改用其他后台控制路径。后续安装使用受支持前台调用。数据库认证和迁移测试必须先取得明确账户及操作范围授权；不读取本机现有应用凭据，不使用root默认密码试探。
