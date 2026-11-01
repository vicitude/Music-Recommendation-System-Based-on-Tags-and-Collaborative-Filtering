# 基础业务实施与验证记录

日期：2026-10-30。范围：基础后端接口，不是完整系统验收。关联排期清单#003、#004。

后续进度：纯推荐引擎与33项算法测试已完成；包含本记录27项基础测试的最新回归合计60项通过，见[推荐验证](recommendation-results.md)。本文其余“下一步/未完成”保留基础接口阶段的时点，不替代最新算法进度。

## 已实现

- 账户：注册、用户名规范化、密码验证、登录、注销、当前用户；注册不自动登录，普通账户不能提交管理权限或数据来源字段。
- 安全：写请求先检查CSRF，再检查登录；停用账户不能继续访问；统一错误字典、UUID请求ID与规格版本响应头。
- 兴趣：0或3—5个有效标签，事务替换、排序返回、非法请求不改变原选择。
- 曲库：公开元数据、关键词与标签联合查询、分页、标签过滤；没有核验播放权的元数据不标为可播放。
- 私有数据：收藏、歌单增删改查、歌单歌曲关系；重试不重复插入、不改首次创建时间；100歌单和500歌曲上限在事务锁后检查。
- Django admin：注册自定义用户管理，origin与onboarding_completed只读；尚无媒体上传/发布表单。
- 前端公共请求客户端：登录/注销后清除旧CSRF缓存，下次写请求重新获取；页面仍是骨架，没有完成页面联调。

20个已接通的OpenAPI operationId：getCsrf、register、login、logout、getMe、getInterests、setInterests、listTags、listSongs、getSong、listFavorites、addFavorite、removeFavorite、listPlaylists、createPlaylist、getPlaylist、renamePlaylist、deletePlaylist、addPlaylistSong、removePlaylistSong。

## 实测结果

| 检查 | 结果 | 边界 |
|---|---|---|
| Django基础业务测试 | 27/27通过 | 进程内SQLite测试数据库；不是MySQL验证 |
| Django system check | 通过 | test_settings；不访问MySQL |
| makemigrations --check --dry-run | No changes detected | test_settings；不执行正式库迁移 |
| 前端typecheck | 通过 | 类型检查，不是页面操作验收 |
| 前端build | 通过 | 保留既有大chunk警告，不新增打包优化范围 |
| 离线规格门禁 | 通过，4项自测通过 | 仅文档与依赖一致性 |

测试覆盖注册/登录/注销、旧CSRF失效、错误密码不披露账户存在性、密码空格保留、输入类型和未知字段拒绝、CSRF顺序、停用账户、JSON/方法/路径错误、64KiB限制、兴趣幂等和回滚、分页和查询边界、私有歌单隔离、收藏和成员关系幂等、下架隐藏、容量上限、故障回滚及媒体路径边界。成功与错误响应使用OpenAPI中的JSON Schema校验选定投影；不是CT-M-001全部分支覆盖。

TC-M-001/002/003/005/014/015已具有对应Django自动化验证。PT-M-005/007/010已有固定输入与seed=42的顺序测试；未覆盖性质文档全部生成空间。TC-M-016仅验证已有写路由的相同优先级，原每日刷新端点未实现，不记该场景完成。Gherkin文件尚未绑定步骤；未宣称behave场景执行通过。

## 复核命令

在项目根目录执行：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=2
& '.\.venv\Scripts\python.exe' -B backend/manage.py check --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -B backend/manage.py makemigrations --check --dry-run --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
npm.cmd run typecheck --prefix frontend
npm.cmd run build --prefix frontend
~~~

test_settings显式改用内存数据库，进程结束即释放；没有读MySQL密码、连接MySQL、创建MySQL库或迁移MySQL数据。测试采用快速密码哈希仅用于隔离测试；正式settings继续使用Django默认安全哈希。测试歌曲均为example.org占位的内存元数据，不读取、复制、删除或播放用户素材。

## 未完成

1. streamSong、recordBehavior、getDaily、refreshDaily四个接口；双路算法、自适应权重、证据解释与快照。
2. SongAdminForm、合法媒体检测、上传与人工发布流程；用户素材版权仍未核验。
3. 前端真实页面、播放器和后端联调；当前页面不代表业务已可操作。
4. MySQL专用账户与库操作授权、真实连接/兼容性、迁移/回滚与并发锁测试；SQLite不证明MySQL兼容或行锁正确。
5. 完整CT/PT、Gherkin步骤、浏览器验收、性能测量、真实推荐实验与论文材料。

下一步可先在不依赖MySQL和素材许可的前提下实现纯推荐计算及数学测试；数据库联调与音频发布仍保留独立授权门槛。
