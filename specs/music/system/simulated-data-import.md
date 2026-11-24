# 模拟用户数据导入说明

## 用途

本项目没有真实用户内测数据，推荐算法的效果验证使用本机生成的模拟账号。这些账号在数据库中被标记为 `origin=SIMULATED`，与真实账号完全隔离：推荐计算按来源分组，模拟账号的行为不会进入真实账号的推荐结果，模拟指标也不会被写成真实用户效果。

## 生成内容

一次默认导入生成 200 个模拟账号，账号名形如 `sim_user_001`：

| 内容 | 数量级 | 说明 |
|---|---|---|
| 模拟账号 | 200 | 8 类音乐画像轮流分配，密码不可登录，除非显式指定 |
| 兴趣标签 | 约 800 | 风格、情绪、场景各取，符合前台 3—5 个标签的规则 |
| 播放行为 | 约 7000 | 每首含 PLAY 与 COMPLETE 或 SKIP，带真实时序时间戳 |
| 收藏 | 约 700 | 优先收藏符合画像的歌曲 |
| 评分 | 约 1600 | 4—5 分为正反馈，2—3 分为中性或弱负反馈 |
| 歌单 | 200 | 每账号一个带画像名称的歌单 |

行为分布不是均匀随机的：符合画像的歌曲更容易被完整听完、收藏和给高分，不符合的更可能被快速跳过。这样协同过滤才有真实的稀疏性和可学习信号。

## 导入步骤

在项目根目录用 PowerShell 执行，密码隐藏输入，不会进入命令历史：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend\seed_local.py --count 200 --seed 42
~~~

常用参数：

| 参数 | 作用 |
|---|---|
| `--count` | 生成账号数量，默认 200 |
| `--seed` | 随机种子，默认 42；同种子结果可复现 |
| `--username-prefix` | 账号名前缀，默认 `sim_user_` |
| `--login-password` | 可选，给模拟账号设置统一本地登录口令，方便登录前台查看推荐 |
| `--check-only` | 只核验专用库与已发布歌曲，不写入任何数据 |

导入是幂等的：相同种子和前缀重复执行不会重复插入，只会补齐缺失记录，不会删除或覆盖你已有的账号、歌曲、收藏和媒体文件。遇到同名但来源不是 `SIMULATED` 的账号会直接停止。

## 前置条件

- 专用库已完成项目迁移（可用 `backend\start_local.py --check-only` 确认）。
- 曲库中至少有一首已发布（active）的歌曲，否则模拟行为无法产生推荐，命令会停止并提示。

## 导出与离线评价

导入后可以把库中模拟行为导出为研究数据集，再用已有的五组方法对比程序计算指标：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend\manage.py export_simulated_dataset --output '.\temp_simulated_dataset'
& '.\.venv\Scripts\python.exe' -B backend\manage.py evaluate_recommender --dataset '.\temp_simulated_dataset\manifest.json' --output '.\temp_simulated_results' --seed 42
~~~

导出数据 `origin=SIMULATED`，报告状态为 `SIMULATED_SELF_TEST`。这组数字可以用于验证算法链路和论文图表占位，不能表述为真实用户效果。

## 清理

如需清掉模拟数据，只删除 `origin=SIMULATED` 的账号及其级联关系；真实账号、歌曲、标签和媒体不受影响。本项目不提供一键清理命令，避免误删；需要时先在后台确认再由人工处理。

