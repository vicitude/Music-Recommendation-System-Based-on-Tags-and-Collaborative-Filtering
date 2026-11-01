# 播放行为采集与幂等验证记录

日期：2026-10-30。关联排期清单#003、#004、#005。代码：backend/music/behavior.py、backend/music/test_behavior.py及API序列化/路由。精确规则见service-contracts.md“行为采集执行边界”。

后续进度：媒体管理与streamSong已实现，新增40项媒体测试、最新177项回归通过，见[媒体验证](media-results.md)。本文“媒体尚未实现”等字样保留行为阶段时点，不代表最新状态。

## 已实现

- POST /api/v1/behaviors/支持PLAY、COMPLETE、SKIP，首次201，规范化载荷完全相同的重传200；23/24个公开操作已接通，streamSong仍未实现。
- User事务锁保护事件写入；同event_id不同载荷或跨用户为409冲突，不回显原事件；同会话不允许换歌或第二次PLAY重置计时，终止后不接受新终止事件。
- 有效时长=min(客户端累计、服务器经过毫秒、歌曲时长)，使用整数毫秒向下取整；COMPLETE还必须同时满足位置与有效时长均达到整数向上取整的80%门槛。
- UUID/类型/枚举/未知字段严格校验，occurred_at和origin由服务器生成。事件重试优先于歌曲下架/终止状态，不更新原有效时长或接收时间。
- PLAY与SKIP不产生正反馈；通过接口接受的COMPLETE可直接被已有推荐适配读取，更新标签画像并过滤近24小时已完成歌曲。多次听完同歌不重复增加矩阵分值。
- 唯一冲突使用savepoint重读；无法归因的数据库异常不伪装成功。失败写入回滚，不制造半条事件或已终止的假状态。

边界：本版行为端按既定契约检查active歌曲，播放许可由尚未实现的stream入口承担。没有真实播放器证据绑定，恶意客户端仍可伪造累计时长；不能宣称反作弊完备。后端不替代浏览器playing/pause/seeking时长累计，后者尚未实现。

## 实测结果

| 检查 | 结果 | 边界 |
|---|---|---|
| 行为测试 | 40/40通过 | 内存SQLite、合成元数据/事件，不播放音频 |
| 全量后端回归 | 137/137通过 | 基础27 + 算法33 + 每日37 + 行为40 |
| Django system check | 通过 | test_settings，不连接MySQL |
| makemigrations --check --dry-run | No changes detected | 无模型/迁移变更，不迁移正式库 |
| 规格门禁 | 通过，4项自测通过 | 文档与已安装依赖一致性 |

测试覆盖100次重传、逐字段冲突、跨用户冲突、UUID规范化、下架后完全重传、切歌与重开会话、缺少PLAY、第二次PLAY、两类终止状态、暂停/拖动反例、80%上下界、微秒向下取整、1ms—24小时歌曲时长、客户端累计限幅、时钟逆行、严格输入、CSRF/认证、模拟来源隔离、插入/终止失败回滚、模拟唯一冲突，以及行为→推荐画像/候选过滤的后端链路。

TC-M-006/007/013已有对应Django API测试；PT-M-001顺序100次重传与PT-M-011两类终止路径通过。PT-M-012新增行为故障回滚，完整关系/快照/线程并发空间未覆盖。唯一冲突分支采用模拟注入，不等于MySQL竞态实测。Gherkin步骤仍未绑定，未声称behave场景通过；前端播放计时、真实推荐效果均未验证。

## 复核命令

从项目根目录执行：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music.test_behavior --settings=config.test_settings --verbosity=2
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
& '.\.venv\Scripts\python.exe' -B backend/manage.py check --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -B backend/manage.py makemigrations --check --dry-run --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

本轮未新增依赖、连接MySQL、读取凭据、读取/导入用户音频、删除文件或操作Git。没有改前端，不把历史构建记作本轮浏览器验收。

## 下一阶段

完成受控媒体管理、文件检测/上传、管理员人工许可与预览核验、streamSong登录权限及Range响应，再联调前端播放器/真实页面。MySQL专用库操作、实际音频发布仍需相应授权与证据；真实并发、完整CT/PT、浏览器、性能及研究实验保留未完成。
