# v39 三路融合与推荐诊断扩展

- 日期：2026-11-08。
- 状态：已实现，真实 MySQL 与浏览器推荐链路验收待单独执行。
- 关键词：三路融合、TF-IDF、User-CF、Item-CF、有效权重、诊断、旧快照兼容。
- 关联模块：推荐、每日推荐、管理员诊断、前端类型、API Schema。
- 变化程度：推荐纯计算与诊断展示更新；无新增迁移、依赖或前端业务页面。

## 摘要

阶段 4 已完成。每日推荐现在同时计算标签内容、User-CF 和 Item-CF 三路分数，并按可用路由自动归一化权重。管理员诊断页展示三路分数、有效权重和来源解释；旧 `CF` 来源与旧快照仍保留读取兼容。

## 固定规则

- 三路固定为 `CONTENT`、`USER_CF`、`ITEM_CF`；`HOT` 只作补位，不计入三路。
- 内容路初始权重使用既有 `alpha_target`；User-CF 与 Item-CF 平分剩余权重。
- 某一路没有正向候选时，该路权重为0，剩余可用路由自动归一化；完全没有个性化信号时保持热门补位。
- `user_cf_score` 与 `item_cf_score` 分别记录两路归一化分数；`cf_score` 保留为两路协同分的兼容合并值。
- 推荐来源新增 `USER_CF` 与 `ITEM_CF`，旧 `CF` 仅作为历史快照兼容值。

## 实现

- `backend/music/recommendation.py` 扩展 `RecommendationResult.route_weights`、三路分数和三路融合。
- `backend/music/daily.py` 支持新来源的每日快照证据校验，同时保留旧 `CF`。
- `backend/music/diagnostics.py` 与后台诊断模板展示用户协同、歌曲协同及其有效权重。
- 更新 `entities.schema.json`、`openapi.yaml` 与前端推荐类型；没有新增数据库字段或迁移。

## 验证

- 推荐、每日推荐、诊断专项测试：87 项通过。
- 后端全量测试：303 项通过。
- 前端测试：68 项通过；类型检查与 Vite 构建通过。
- 文档门禁：27 个 API、16 组场景、12 个性质检查通过。
- 实体 Schema JSON 可解析；`git diff --check` 通过。
- 构建保留既有大包体积警告。
- 未完成：未连接真实 MySQL、未执行真实库迁移、未进行浏览器点击复验；场景/时段动态权重尚未实施。

