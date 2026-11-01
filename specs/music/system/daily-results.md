# 每日推荐接口与快照验证记录

日期：2026-10-30。关联排期清单#003、#005。代码：backend/music/daily.py、backend/music/media.py、backend/music/test_daily.py及API路由。契约见service-contracts.md“每日推荐适配与快照执行边界”。

后续进度：行为接口与状态机已实现，新增40项行为测试、最新137项回归通过，见[行为验证](behavior-results.md)。本记录“行为仍未实现”等文字保留每日接口完成时点，不代表最新状态。

## 已实现

- GET /api/v1/recommendations/daily/ 与 POST /api/v1/recommendations/daily/refresh/，公开API已接通22/24个操作。未实现streamSong与recordBehavior。
- 从项目ORM读取同来源有效用户、当前收藏、早于请求时刻的COMPLETE、兴趣、标签和歌曲；复用纯推荐引擎。PLAY/SKIP、不匹配来源、未来反馈和停用邻居不计入。
- 按请求统一now的上海日期保存快照；首次revision=1，重复GET不重算，成功刷新revision加1。User→Snapshot顺序加锁与唯一冲突savepoint重读已写入实现，尚未在MySQL实测。
- 每次生成后60秒内POST限流，包含首次GET创建；跨午夜仍按用户最新生成时间判断，429附Retry-After，拒绝不写库。
- 返回前重新过滤下架、失去播放许可、文件无效、新收藏、近24小时完成、标签停用/改名/移除与不实解释；只重编rank，不补位或修改存储快照。
- 每日路由成功与错误均带private,no-store；保持会话、CSRF顺序、统一错误和请求ID。
- 曲库序列化和推荐适配共用受控媒体路径校验，避免两处判定漂移。函数只查路径/文件存在，不读取音频、不替代发布前媒体校验或人工许可核验。

## 实测结果

| 检查 | 结果 | 边界 |
|---|---|---|
| 每日推荐测试 | 37/37通过 | 内存SQLite、合成元数据、模拟文件存在；不是素材播放或MySQL并发验证 |
| 全量后端回归 | 97/97通过 | 基础27 + 纯算法33 + 每日37 |
| Django system check | 通过 | 显式test_settings，无MySQL连接 |
| makemigrations --check --dry-run | No changes detected | 无模型/迁移变更，无正式库迁移 |
| 规格门禁 | 通过，4项自测通过 | 文档与依赖一致性 |

37项测试包括：首次GET/POST、重复GET、0/59/59.01/60/61秒刷新、跨午夜限制与归档、CSRF优先、登录隔离、输入拒绝、CONTENT/CF/HYBRID/HOT响应、Daily/Error Schema、失效过滤、标签解释更新、无补位、空快照稳定性、历史/未来/来源/停用用户读取边界、受控路径异常、首次插入/刷新故障回滚、唯一冲突模拟和时钟逆行。

TC-M-009/010/011/016已有对应Django API验证；Gherkin仍无步骤绑定，不能称behave场景运行通过。TC-M-008精确0.68算例仍在纯算法层，未新增同算例HTTP测试。PT-M-008顺序边界通过，并发2—20次未验证；PT-M-012仅补充快照故障注入，完整关系/行为/并发空间未完成。CT-M-001全部24接口分支、DB-M测试、性能与真实推荐质量实验仍未完成。

## 复核命令

从项目根目录执行：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music.test_daily --settings=config.test_settings --verbosity=2
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
& '.\.venv\Scripts\python.exe' -B backend/manage.py check --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -B backend/manage.py makemigrations --check --dry-run --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

没有新增依赖、MySQL连接/凭据读取、用户素材读取/导入、文件删除或Git操作。未更改前端，未把历史构建或不存在的浏览器操作当作本轮验收。

## 仍需完成

1. 管理员媒体上传/校验/人工发布，实际授权文件的播放与Range接口；当前统计不代表有合法可播放曲库。
2. 行为事件采集、幂等与播放状态机。当前推荐测试的COMPLETE均为合成数据库事实，不能证明已采集真实收听。
3. 前端真实页面、播放器与每日接口联调。
4. 明确项目账户/库操作授权后，再做MySQL连接、迁移和真实并发；内存测试不替代该门槛。
5. Gherkin绑定、完整CT/PT、性能、真实研究数据和论文实验。
