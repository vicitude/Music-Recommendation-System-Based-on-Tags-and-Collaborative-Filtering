# 本机开发环境核验记录

核验日期：2026-10-29。范围：现有文件、命令版本、注册表、运行服务、端口与Python包元数据。未安装软件、未联网下载、未修改PATH、未启动服务、未连接数据库、未尝试密码、未创建虚拟环境。核验过程中npm全局清单查询自行生成了诊断日志，不等于文件系统完全零写入；没有改动软件或配置。

本文件是安装前历史观察；用户随后批准的安装及当前依赖状态见[安装记录](installation.md)，不将本表“缺包”直接作为安装后的结论。

## 1. 已观察到的环境

| 项目 | 观察结果 | 结论 |
|---|---|---|
| 系统 | Windows 11家庭中文版，10.0.22631，64位 | 单机开发平台存在，未进行应用负载测试 |
| 可见内存 | 15.3 GiB | 只记录容量，不据此保证性能指标 |
| D盘剩余 | 约16.4 GiB | 安装和曲库前重新检查，不预留或清理空间 |
| Node.js | C:/NodeJs/node.exe，v24.21.0 | 版本命令运行成功；尚无Vite工程或依赖兼容验证 |
| npm | C:/NodeJs/npm.cmd，11.19.0 | 版本命令成功；npm list -g失败，原因是全局前缀目录不存在，不代表项目依赖安装必然失败 |
| Git | C:/Git/cmd/git.exe，2.49.0.windows.1 | 可执行；项目没有初始化Git，未更改Git配置 |
| Python 3.12 | C:/Users/will vicissitude/AppData/Local/Programs/Python/Python312/python.exe，3.12.0 AMD64 | -I -B探针执行成功，有venv模块；存在pip 23.2.1、NumPy 2.4.6、PyYAML 6.0.3的包元数据 |
| Python 3.13 | D:/Python313/python.exe，3.13.17 AMD64 | -I -B探针执行成功，有venv模块，pip 26.2.2；未发现项目所需框架包 |
| 默认python | 指向WindowsApps别名 | 不是本次验证通过的解释器入口，不使用该路径建立项目环境 |
| python3.12命令 | 指向.local/bin下uv跳板 | 实测失败：uv无法启动目标解释器；不修改该跳板，用真实绝对路径 |
| MySQL | C:/Program Files/MySQL/MySQL Server 9.2/bin/，mysql与mysqld均报告9.2.0 | 已有数据库软件；不再断言未安装或要求重装 |
| MySQL服务 | MySQL92运行中，引用D:/Mysql/my.ini；3306监听在:: | 未读取配置正文、未核验用户/权限/数据库/认证/TLS，不据此判定可连通或可迁移；外部可达性未测试 |
| 开发端口 | 本次未观察到5173和8000监听 | 瞬时检查，不保证未来空闲 |

两个真实Python解释器的元数据均未发现：Django、djangorestframework、SciPy、mysqlclient、PyMySQL、jsonschema、openapi-spec-validator、behave。发现包元数据不等于导入和二进制兼容验证成功；其他未知目录和其他工具私有环境没有全盘扫描，不声称全机不存在这些包。

项目无package.json、package-lock.json、pyproject.toml、requirements文件、manage.py、.venv和CI工作流。没有应用可供构建或测试。

## 2. 技术路线与实际环境的区别

- Python：建议在已有真实解释器上建立项目隔离环境，不改默认入口、不复用全局包；3.12.0补丁较旧，是否保留或更新必须先确认。3.13.17是本机另一候选，不能仅凭版本号就宣称框架和驱动兼容。
- 数据库：方案目标仍为MySQL 8.x，本机是9.2.0。优先不干扰现有服务；需在“验证9.2后另行批准变更目标”与“另行部署8.x”之间明确选择。当前不降级、不卸载、不覆盖现有实例、不创建数据库。
- npm：全局目录缺失只影响本次全局清单探测；不创建目录、不改prefix、不安装全局工具。未来用项目内依赖与锁文件，安装前确认。
- 精确依赖：尚无已解析锁文件，不能从运行时版本推导Django、Vite或数据库驱动的可用版本。未查询远端包索引，不编造“已验证最新版本”。

## 3. 下一次操作必须先确认的范围

1. 批准所用真实Python解释器及是否更新；批准创建项目.venv及项目内依赖，不做全局安装。
2. 确认复用MySQL 9.2的兼容验证方向或独立8.x实例。已有数据库连接使用用户自行提供的专用账户，不索取或输出现有root密码，不对已有业务库操作。
3. 安装批准前给出依赖类别、用途、隔离路径、所需网络和系统影响；批准后才能解析并锁定完整版本与执行导入测试。
4. 数据库连接、建库和迁移分别取得范围授权；只读版本命令不能替代连接/事务/迁移验证。
5. 安装或建库均没有获得本轮授权。学校要求、合法音频及研究数据继续保留为外部门槛。

## 4. 本轮可复核的无安装命令

在PowerShell执行，解释器使用真实绝对路径；这些命令不创建项目环境：

~~~powershell
node --version
npm.cmd --version
git --version
& 'C:/Users/will vicissitude/AppData/Local/Programs/Python/Python312/python.exe' -I -B -c 'import sys; print(sys.version); print(sys.executable)'
& 'D:/Python313/python.exe' -I -B -c 'import sys; print(sys.version); print(sys.executable)'
& 'C:/Program Files/MySQL/MySQL Server 9.2/bin/mysql.exe' --version
Get-Service -Name MySQL92
~~~

不再重复npm全局清单查询来证明项目安装能力；不运行会自动下载的npx、corepack准备命令或缺失Python运行时的自动安装器。
