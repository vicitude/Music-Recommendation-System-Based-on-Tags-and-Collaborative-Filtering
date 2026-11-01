# v6 · 已批准隔离依赖安装与部分完成记录（2026-10-29）

- 状态：活跃。
- 关键词：安装授权、隔离环境、依赖锁、下载超时、MySQL驱动。
- 相关模块：环境、依赖、兼容验证。
- 关联文档：[安装记录](../specs/music/system/installation.md)、[原环境记录](../specs/music/system/environment.md)。
- 变化程度：新增项目内环境、依赖清单及前端锁，不开发业务、不改系统、不连接数据库。

## 摘要
用户回复“批准”，授权创建Python3.13隔离环境并安装项目依赖、优先验证现有MySQL9.2。前端与mysqlclient已安装并完成有限检查；大包下载反复超时，Python全量环境未就绪，不虚构完整锁或兼容结论。

## 决策
1. 新增requirements.in、requirements-dev.in、frontend/package.json、package-lock.json及.gitignore；精确结果唯一维护于installation.md。
2. 后端只使用预编译wheel，前端忽略安装生命周期脚本；安装进程已停止，不遗留并行安装器。
3. 本轮没有数据库连接或SQL。MySQL9.2实际兼容仍缺Django和认证测试；原8.x目标尚不因此修改。
4. 当前不满足正式实施门槛，#002与#003仍未完成；已授权部分不抹除未完成项。
5. 此前“安装需另行批准”的门槛，对本次明确范围已经获得批准；新增范围仍须确认。
