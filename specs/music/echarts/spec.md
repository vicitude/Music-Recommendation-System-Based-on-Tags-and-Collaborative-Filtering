# SPEC-ECHARTS-001：472 首模拟实验看板

## 0. 元数据

状态：已实现（离线门禁通过、浏览器验收未执行）；版本 v1.1.0；PO 项目用户，TL/QA 主会话。绑定 `frontend/src/pages/EvaluationPage.vue`、`frontend/src/data/catalogEvaluation.ts`、`frontend/src/data/sim472-seed42-v3-report.json`、`frontend/tests/catalog-evaluation.test.mjs`。无 API 路由与数据库迁移。下列 Gherkin 绑定 Node 现有测试运行器和浏览器验收，不引入 Cucumber。门禁见 §8。

## 1. 术语

| 术语 | 英文名 | 类型 | 定义 | 代码映射 | 数据库映射 | 示例 |
|---|---|---|---|---|---|---|
| 评价视图 | Cohort | 枚举 | `overall, cold_start_0, light_1_9, regular_10_29, heavy_30_plus`（顺序固定） | `cohortLabels` | 无 | 零历史组 |
| 方法 | Method | 枚举 | `HOT, CONTENT, USER_CF, ITEM_CF, NCF, FIXED_4, ADAPTIVE_4, ADAPTIVE_4_RERANK, ADAPTIVE_NO_NCF`（顺序固定） | `methodLabels` | 无 | 自适应融合＋重排 |
| 指标 | Metric | 枚举 | `precision, recall, f1, hit, ndcg, coverage, diversity, novelty, unexpectedness, serendipity`（顺序固定） | `metricLabels` | 无 | F1@10 |
| 路由 | Route | 枚举 | `content, user_cf, item_cf, ncf`（顺序固定） | `routeLabels` | 无 | 神经协同 |

## 2. 验收场景

```gherkin
功能: 查看模拟推荐评价
  场景: 打开看板
    假设报告是固定种子 42 的 472 曲库正式离线模拟
    当打开 #/evaluation
    那么默认显示全体的 F1@10、9 种方法与测试目标 200 人
  场景: 切换组别和指标
    当选择零历史组和惊喜度
    那么图中不绘制缺值且表中显示破折号
    且真实数值 0 不转换为缺值
  场景: 导出
    当点击导出原始模拟报告
    那么下载完整原始报告字节而非当前筛选子集
  场景: 离开页面
    当卸载看板
    那么释放已创建图表并移除 resize 监听
```

## 3. 接口

保留 `#/evaluation` 路由及其现有访问条件。静态导入，无 HTTP/OpenAPI 与请求权限变更。按钮下载 `sim472-seed42-v3-report.json`，MIME `application/json`，例如选中零历史组后仍导出九种方法全部结果。

## 4. 数据模型

前端复制 `sim472-seed42-v3/report.json` 确切字节，固定 SHA-256 `06e1781c9efcb698c925f5b85aa4dcff065b17b59352a9b882b3878d0a35a2f0`。源契约为 SPEC-SIM472-001 §4；展示 `origin=SIMULATED`、`seed=42`、`configuration.k=10`、`scene_enabled=false`、`tuned=false`、`groups` 与 `split.train/validation/test`。报告未内嵌歌曲总数，由本次冻结目录固定为 472；用户数从组人数求和，行为数由三窗口相加。`methods[method].overall` 及 `.groups[cohort]` 均有 `users` 与 §1 指标，按报告保留 `number | null`；零历史组的后两项因没有训练历史是 `null`。`route_weights_by_user` 每个模拟用户有四个数字权重，全零表示热门兜底，不参与路由均值。其余报告字段仅保留在原样导出内。

## 5. 展示规则

`cohort=overall`、`metric=f1` 默认。`evaluationRows(cohort: Cohort): Array<{name: Method; label: string; values: Metrics}>` 按 §1 方法顺序映射报告；`formatPercent(value: number | null): string` 空值显示 `—`，其他值乘 100 保留两位小数并加 `%`。指标图用横向柱、按表同序、数值轴从零开始并随数据确定上限；全空时不绘制数值并提示「该分组没有此指标的数据」。组别切换同步更新图、表和测试目标人数；指标切换只改变主图及其标题。全局样本分组饼图、全局路由平均堆叠条不随筛选改变。路由平均对每个非全零用户等权（175 人），说明排除 25 人热门兜底；四项均值不再归一化。删除旧 40 首看板引用、旧偏好与八时段展示，不删除历史文件。结果注记说明带噪标签、关闭场景、验证集未调参、不是实际用户效果，并对照重排前后 F1、多样性、覆盖率与排序质量；不改算法。切换不销毁图表，挂载初始化，卸载清理；图表外表格提供等价指标数据。

### Properties

P-ECH-04（§2 切换）：对 5 个视图与 9 种方法，`evaluationRows` 返回相应原值，含 `null` 与数值 0；枚举全量扫描绑定 PT-ECH-004。

## 6. 错误与日志

无新增业务错误码、日志或兜底假数据。报告缺失导致构建失败；字节或固定结构变更由 CT-ECH-005 阻断。示例：单一字节改动导致 SHA-256 不匹配。

## 7. 测试追溯

| 来源 | 需求 ID | 类型 | 测试 ID | 状态 |
|---|---|---|---|---|
| §4、§6 | REQ-ECH-05 | 契约 | CT-ECH-005 | 已自动化 |
| §2、§5 | P-ECH-04 | 性质 | PT-ECH-004 | 已自动化 |
| §2、§5 | REQ-ECH-06 | 单元 | UT-ECH-006 | 已自动化：检查权重分母与空值格式 |
| §2、§5 | REQ-ECH-07 | 验收 | TC-ECH-007 | 未自动化：无浏览器自动化接入，部署后手动验收筛选、下载与窄屏 |

## 8. 门禁

在 `frontend` 执行 `npm run test`、`npm run typecheck`、`npm run build`，要求三者退出码均为 0；CT-ECH-005 核验字节摘要、九方法结构、四组人数。浏览器验收不以构建通过代替。

## 9. 假设、约束与版本

依赖既有 Vue/ECharts/Vite 和浏览器 Blob/URL API。不改库、依赖、端口、真实推荐或历史实验文件。示例：构建从前端目录读取内置报告，即使不运行后端也可通过。不伪造提交号；版本历史由 Git 记录，本轮不提交。
