# 离线推荐评价执行说明

## 当前状态

评价入口已经实现数据清单校验、真实时间戳切分、测试目标构造、五组方法统一运行和指标汇总；尚未连接公开研究数据，也不会把线上演示库或模拟行为自动当成真实效果实验。

## 数据准备

在独立实验目录创建 `manifest.json` 和 `data.json`。`manifest.json` 必须包含：

- `manifest_version`: 固定为 `v1`。
- `source`: 数据来源名称。
- `license_evidence`: 许可或研究使用依据说明。
- `origin`: `REAL` 或 `SIMULATED`。
- `timezone`: 时间戳使用的时区。
- `timestamps_are_real`: 必须为 `true`，不能用随机时间替代。
- `data_file`: 相对于 manifest 的数据文件路径，且必须位于同一目录下。

`data.json` 必须包含三个数组：

```json
{
  "songs": [{"song_id": 1, "tag_ids": [10, 20]}],
  "users": [{"user_id": 1, "interest_tag_ids": [10]}],
  "interactions": [
    {"user_id": 1, "song_id": 1, "occurred_at": "2026-01-01T12:00:00+00:00", "positive": true}
  ]
}
```

时间切分使用全局时间顺序：前70%训练、随后10%验证、最后20%测试；同一时间戳不会被拆到不同分区。少于10条交互、时间戳无时区或时间切分导致空分区时，命令直接失败。

## 执行命令

从项目根目录执行：

```powershell
& '.\.venv\Scripts\python.exe' backend/manage.py evaluate_recommender `
  --dataset 'D:\研究数据\music\manifest.json' `
  --output 'D:\研究数据\music\results' `
  --seed 42
```

当前输出 `evaluation-scaffold.json`，包含数据来源、分区边界、测试目标用户、HOT、CONTENT、USER_CF、FIXED、ADAPTIVE 五组方法及指标。`origin=SIMULATED` 时状态标记为模拟自检，只有完成真实数据字段映射审查后，报告中的指标才可作为论文实验结果使用。

## 指标口径

- `Precision@10`：命中数 / 10，不因推荐不足10首缩小分母。
- `Recall@10`：命中数 / 测试目标歌曲数。
- `Hit@10`：是否至少命中1首。
- `F1@10`：Precision@10 与 Recall@10 的调和平均。
- `NDCG@10`：二值相关度，按推荐位置折损。
- `Coverage`：被推荐歌曲并集 / 共同候选歌曲数。
- `Diversity`：同一推荐列表歌曲标签集合的平均 Jaccard 距离。
- `Novelty`：推荐列表中相对用户训练期未出现歌曲的平均比例。
- 无测试目标的用户不进入平均指标，单独报告数量。

用户分组按训练期正向交互数量划分：`cold_start_0`、`light_1_9`、`regular_10_29`、`heavy_30_plus`。每组独立输出 Precision、Recall、F1、Hit、NDCG 和 Coverage；没有该组用户时保留 `users=0` 和空指标。

模拟数据与真实数据必须分开输出；模拟结果只能证明程序机制可运行，不能写成真实用户效果提升。
