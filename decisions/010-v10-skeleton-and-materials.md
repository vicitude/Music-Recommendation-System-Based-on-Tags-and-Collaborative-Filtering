# v10 · 项目骨架与外部素材登记（2026-10-29）

- 状态：活跃。
- 关键词：项目骨架、素材库、音频、MIDI、Vue、Django。
- 相关模块：实现、媒体、前端、后端。
- 关联文档：[实施范围](../specs/music/system/implementation-scope.md)、[素材清单](../specs/music/system/material-manifest.json)、[安装记录](../specs/music/system/installation.md)。
- 变化程度：开始已确认的项目骨架实施，登记外部素材引用；不连接数据库、不迁移、不复制素材。

## 已完成
1. 复用既有MySQL配置方向，但未使用账户、未连接、未建库。
2. 检查 D:\\AAA素材库\\song 与 D:\\AAA素材库\\midi：音频候选49个、MIDI文件88个，结构头检查通过；工程只保存只读来源路径与样本清单。
3. 生成Django后端骨架、模型和 music/migrations/0001_initial.py；manage.py check通过。makemigrations期间尝试检查迁移历史，因示例账户无密码收到1045警告，未执行迁移。
4. 生成Vue/Vite前端骨架、hash路由、首页视觉和API客户端；frontend typecheck与build通过。构建有大chunk提示，不影响本轮骨架通过。

## 素材限制
素材版权、播放权和研究使用权均为UNVERIFIED_USER_SUPPLIED；不把素材直接标成公开可用，不上传、不复制、不打包传播。音频只在用户确认许可并完成管理员人工核验后进入 playback_allowed=true；MIDI目前作为后续可选曲谱/元数据来源，不进入音频播放训练事件。

## 当前阻塞
数据库账户/专用库未确认，不能运行migrate；合法授权标记未确认，不能发布或对外演示音频；推荐接口、用户行为服务、页面真实API联调、测试步骤和数据库测试尚未实现。
