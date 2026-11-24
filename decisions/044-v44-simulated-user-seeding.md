# v44 模拟用户数据生成与本机导入

- 日期：2026-11-08。
- 状态：已实现，真实专用库导入由项目所有者在本机执行。
- 关键词：模拟用户、行为生成、幂等导入、离线评价、来源隔离。
- 关联模块：曲库、行为、评分、推荐、实验。

## 背景

项目没有真实用户内测数据，用户明确要求直接向项目专用 MySQL 写入一批有差异的模拟用户，用于验证推荐算法效果；模拟结果不得冒充真实实验结论。

## 决策

1. 新增 `seed_simulated_users` 管理命令，按 8 类音乐画像生成带差异的账号、兴趣、播放完成/跳过、收藏、评分和歌单；行为时间戳按真实时序分布，使协同过滤存在可学习信号。
2. 新增 `backend/seed_local.py` 本机入口，沿用既有安全模式：隐藏输入密码、只允许 `127.0.0.1` 的专用库与专用账户、不删除任何数据、可先 `--check-only` 核验。
3. 导入幂等且只作用于 `origin=SIMULATED` 账号；遇到同名真实账号直接停止。
4. 新增 `export_simulated_dataset` 命令，把库中模拟行为导出为 `manifest.json` 与 `data.json`，供 `evaluate_recommender` 计算五组方法指标。
5. 模拟账号与真实账号按 `origin` 分组计算推荐，模拟行为不进入真实账号的推荐结果；模拟指标不得写成真实用户效果。

## 实现

- `backend/music/management/commands/seed_simulated_users.py`
- `backend/music/management/commands/export_simulated_dataset.py`
- `backend/seed_local.py`
- `backend/music/test_seed_simulated_users.py`
- `specs/music/system/simulated-data-import.md`

## 验证

- 后端全量测试：317 项通过（新增 5 项覆盖生成规模、幂等、登录口令、每日推荐可解释性与导出数据集可评分）。
- 内存库实测：200 账号、800 兴趣关系、7260 条播放行为、723 收藏、1600 评分、200 歌单、1600 歌单歌曲。
- 模拟用户每日推荐可生成，且首条来源不是热门兜底，说明内容与协同分支均生效。
- 导出的模拟数据集可直接被五组方法评价程序读取并产出指标。
- 未连接真实专用库，未写入任何真实数据；本机导入需项目所有者输入密码执行。

