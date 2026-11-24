# v087 ECharts实验看板

闭环：BACKLOG #005 ECharts可视化子项。用户2026-11-16表示“下一步”，继续已确认顺序。

## 实现
仅在frontend项目新增固定版本`echarts@5.6.0`，更新frontend/package.json与package-lock.json；未全局安装、未升级其他项目依赖。新增specs/music/echarts/spec.md、tasks.md、self-check.md，规格自检17/17。

frontend/src/pages/EvaluationPage.vue将原CSS环形图、权重条和指标CSS柱条替换为按需ECharts：PieChart展示Top5模拟偏好，stacked Bar展示ADAPTIVE平均路由权重，Bar展示所选指标方法对比。保留数据表、八时段表、模拟边界说明和JSON导出。使用onMounted初始化，指标切换重绘，窗口resize调用resize，onBeforeUnmount逐实例dispose并移除监听。

## 验证
前端测试191/191通过；vue-tsc类型检查通过；Vite构建通过，2197 modules transformed，产物JS 1,594.51 kB/gzip 528.90 kB。构建仍有既有/新增大分包警告（超过500 kB），本轮未擅自拆包。规格门禁未访问数据库。

## 限制
看板仍使用`frontend/src/data/simulatedEvaluation.ts`中的C1/旧40歌曲模拟结果（seed42），不代表472歌曲新实验或真实用户效果；本轮未生成新模拟数据、未写业务库、未迁移、未重启服务、未提交。ECharts真实浏览器视觉验收仍需启动5173后由用户检查。
