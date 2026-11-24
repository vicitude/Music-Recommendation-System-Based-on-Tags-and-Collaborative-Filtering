# NCF实施任务
1. 按spec.md§4/5实现ncf.py的校验、两层tanh网络、完整反向传播与Adam。
2. 实现fit/predict及JSON save/load；推荐compute_ncf使用8项LRU，保持原调用入口与冷启动。
3. 按§7的9个ID实现测试，修订旧minmax断言，执行纯算法与Django内存回归。
4. 记录结果及未完成边界，不生成正式472数据、不安装依赖、不提交。
