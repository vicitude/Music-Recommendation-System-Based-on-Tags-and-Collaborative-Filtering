# v085 神经协同过滤MLP与模型制品

闭环：BACKLOG #005中NCF神经网络实现子项，不关闭整项。用户2026-11-16同意先NCF、再多样性/惊喜度及ECharts、再新模拟实验。

## 实现
backend/music/ncf.py提供fit_ncf/predict_ncf/save_ncf/load_ncf：8维用户与歌曲embedding拼接→16维tanh→8维tanh→sigmoid，BCE与Adam，默认30epoch、seed42、学习率.01。使用既有NumPy，无新安装。属于NCF的MLP分支，不冒充NeuMF联合预训练。
backend/music/recommendation.py替换原logistic MF，训练与预测分离，LRU最多8份，同完整矩阵/曲库/超参跨用户复用；矩阵或曲库变更重新训练。制品为校验的JSON，拒绝覆盖及超过16MiB输入，不自动加载外部制品到在线服务。历史正例保留，零历史无NCF结果，单候选返回有效概率，未知用户/歌曲不伪造embedding结果。原同origin/cutoff过滤不变。

## 真实执行验证
- 纯算法专项59/59（新增9项，含全部八类参数的有限差分、降损、确定性、候选闭包、制品往返与缓存），0.780秒。
- 后端全量465/465，62.673秒，config.test_settings SQLite内存；不等于MySQL/浏览器实机。
- 规格门禁36 operations/16场景组/12性质、4自测与环境检查通过；定点diff --check通过。
- 5用户/6歌曲手工构造训练样本100epoch：BCE 0.692609413530939→0.011458090728728073，训练耗时0.04617秒。仅证明网络可训练，不证明正式推荐效果或472曲库耗时。
- 首轮59项有1条旧HOT断言失败；全量首轮465项有1条旧纯内容权重断言失败。因新NCF单候选概率非零，改为隔离前后全结果相同及邻居两路零，非放宽数据隔离；复跑通过。
- 一个git diff --no-index NUL命令因Windows路径报Could not access 'backend/NUL'，未修改文件；正常git diff已查看。无业务库写入、迁移、依赖变更、提交、服务重启。

## 边界与后续
未生成正式472模拟数据/训练制品，旧D2评价不代表新模型结果。模型缓存为进程内，仍会在新输入首次训练，不宣称全局离线部署。训练未观测项采样为负仅是假设，正反馈强度本阶段二值化。JSON结构校验不证明来源真实性，fingerprint是训练输入标识，不是签名。
标签复核仍未完成；下一阶段实现多样性/惊喜度排序及对应指标与实验消融；ECharts需先确认依赖安装；正式模拟评价需统一数据快照、候选与时间切分。
规格：specs/music/ncf/spec.md、tasks.md、checklist.md、self-check.md。
