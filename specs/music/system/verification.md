# 离线文档门禁

门禁实现为verify_spec.py。它不属于bootstrap可选verify-matrix/drift-inventory，不安装钩子、不连接数据库、不生成应用，也不运行业务场景。源文件中所有检查均是文档和已安装环境的一致性检查。

## 当前可执行命令

在项目根目录使用已安装隔离环境：

~~~powershell
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
& '.\.venv\Scripts\python.exe' -I -B -m pip check
~~~

退出0表示本次文档门禁通过；退出1表示缺文件、引用/Schema/OpenAPI错误、重复编号、映射漂移、锁文件不匹配或自测失败。--self-test运行4个拒绝损坏输入的测试，不是TC-M业务验收或PT-M业务性质测试。--check-environment核对Python3.13与requirements.lock逐包版本，以及前端manifest和lock入口一致性；不证明第二环境重装可复现。

## 检查范围

- OpenAPI3.1文档合法；11份实体Schema元模式合法且分文件引用可解析。
- 10段正文结构、16组场景ID、12项性质及对应PT编号均被追溯。
- 24个operationId唯一，path参数、API绑定method/path/status一致。
- 迁移计划的每一业务实体字段集合、列名、nullable、default、长度、枚举及范围与实体Schema一致。
- 本规格Markdown文件与项目入口链接可达；歧义短语使用verification-contract.json的穷举清单检查。

不会将单字“等”或“约”机械判为失败，因为“幂等”“契约”“约束”是已定义术语；完整短语清单已明确。清单之外的语义歧义仍需人工审查，不能声称脚本证明零自由发挥。

## CI接入设计

当前未初始化Git、未选择CI服务，不创建宿主钩子或伪造已启用流水线。未来CI使用Windows、Python3.13.17与Node24.21.0，独立环境安装requirements.lock后执行上述脚本，再执行pip check与npm ci --ignore-scripts。依赖安装本身需允许网络，文档验证离线执行。该接入设计尚未在干净CI运行。

实施阶段的分层门禁：阶段0运行本文件命令；阶段1运行Django system check、makemigrations --check、API单元/契约测试；阶段2运行npm run typecheck与npm run build；阶段3专用测试库获授权后运行migrate --plan、迁移回滚与DB-M测试；阶段4绑定Gherkin步骤并运行TC/PT。缺少对应产物时该阶段状态为BLOCKED，不是SKIPPED-PASS。CI接入后按同序执行。

基础27项见[实施验证](implementation-results.md)，算法33项见[推荐验证](recommendation-results.md)，每日37项见[每日验证](daily-results.md)，行为40项见[行为验证](behavior-results.md)，媒体40项及最新177项回归见[媒体验证](media-results.md)。独立推荐测试不加载Django和数据库，全量命令使用test_settings，不访问MySQL，不表示真实媒体、MySQL迁移/并发或全部场景通过。
