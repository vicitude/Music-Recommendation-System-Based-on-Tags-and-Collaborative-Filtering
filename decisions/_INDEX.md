# 决策索引

按关键词定位后读正文，不默认加载整个目录。一决策一文件，三位序号递增并对应 vN。新增决策同步索引，被替代记录保留并标注后继编号。

| 文件 | 版本 | 关键词 | 状态 | 相关模块 |
| [089-v089-catalog472-dashboard.md](089-v089-catalog472-dashboard.md) | v089 | 实验看板、472首、九方法、分组、原始报告导出 | 前端离线验证通过；待浏览器实机 | 前端、评价 |
| [088-v088-catalog472-simulation.md](088-v088-catalog472-simulation.md) | v088 | 472曲库、200模拟用户、九方法、NCF消融、重排对照、字节复现 | 模拟实验完成；83项相关回归，非真人效果 | 推荐、评价 |
| [087-v087-echarts-dashboard.md](087-v087-echarts-dashboard.md) | v087 | ECharts、实验看板、饼图、权重图、指标图、191项前端回归 | 已实现；旧模拟数据，待浏览器视觉验收 | 前端、验证 |
| [086-v086-diversity-serendipity-rerank.md](086-v086-diversity-serendipity-rerank.md) | v086 | 多样性、惊喜度、MMR重排、66项回归 | 活跃；默认重排接入，478项内存回归，正式效果未验 | 推荐、验证 |
| [085-v085-neural-ncf.md](085-v085-neural-ncf.md) | v085 | 真正NCF、MLP、Adam、模型保存读取、缓存、465项内存回归 | 活跃；非正式472效果结论 | 推荐、验证 |
|---|---|---|---|---|
| [001-v1-init-music-workspace.md](001-v1-init-music-workspace.md) | v1 | 初始化、单人、轻量、文档先行 | 活跃 | 工作区、协作、排期 |
| [002-v2-innovation-scope.md](002-v2-innovation-scope.md) | v2 | 创新点、范围、冷启动、自适应融合、可解释推荐 | 活跃 | 需求、算法、实验、答辩 |
| [003-v3-tech-data-strategy.md](003-v3-tech-data-strategy.md) | v3 | 技术选型、Vue、Django、MySQL、数据许可、模拟数据 | 活跃 | 架构、播放、算法、实验 |
| [004-v4-implementation-spec-proposal.md](004-v4-implementation-spec-proposal.md) | v4 | Spec、接口契约、验收、自检、实施门槛 | 活跃 | 规格、API、推荐、实验 |
| [005-v5-local-environment-boundaries.md](005-v5-local-environment-boundaries.md) | v5 | 本机环境、只读检查、Python、MySQL、播放累计 | 活跃 | 环境、规格、行为、验收 |
| [006-v6-isolated-dependency-install.md](006-v6-isolated-dependency-install.md) | v6 | 安装授权、隔离环境、依赖锁、下载超时 | 活跃 | 环境、依赖、兼容验证 |
| [007-v7-dependency-retry-complete.md](007-v7-dependency-retry-complete.md) | v7 | 安装完成、Python锁、契约验证、数据库边界 | 活跃 | 环境、依赖、规格 |
| [008-v8-spec-contract-gate.md](008-v8-spec-contract-gate.md) | v8 | 迁移设计、服务签名、行为性质、离线门禁 | 活跃 | 规格、数据、验证 |
| [009-v9-consolidated-implementation-scope.md](009-v9-consolidated-implementation-scope.md) | v9 | 实施范围、三项收尾、开发门槛、数据库授权 | 活跃 | 实现、前端、数据库、验收 |
| [010-v10-skeleton-and-materials.md](010-v10-skeleton-and-materials.md) | v10 | 项目骨架、素材库、音频、MIDI、Vue、Django | 活跃 | 实现、媒体、前端、后端 |
| [011-v11-basic-api-verification.md](011-v11-basic-api-verification.md) | v11 | 账户、CSRF、兴趣、收藏、歌单、隔离测试 | 活跃 | 后端、验证、前端请求客户端 |
| [012-v12-pure-recommendation-engine.md](012-v12-pure-recommendation-engine.md) | v12 | 标签画像、User-CF、自适应融合、冷启动、解释证据、算法测试 | 活跃 | 推荐、验证 |
| [013-v13-daily-snapshots.md](013-v13-daily-snapshots.md) | v13 | 每日推荐、快照、刷新限流、跨日、解释过滤、ORM适配 | 活跃 | 推荐、API、验证、媒体路径 |
| [014-v14-behavior-events.md](014-v14-behavior-events.md) | v14 | 播放事件、幂等、状态机、有效时长、回滚、行为推荐链路 | 活跃 | 行为、推荐、API、验证 |
| [015-v15-media-admin-and-stream.md](015-v15-media-admin-and-stream.md) | v15 | 媒体上传、人工核验、草稿预览、WAV、MP3、OGG、Range | 活跃 | 媒体、管理后台、API、验证 |
| [016-v16-frontend-and-single-player.md](016-v16-frontend-and-single-player.md) | v16 | Vue页面、单播放器、收藏、歌单、推荐解释、CSRF、播放累计 | 活跃 | 前端、行为、推荐、验证 |
| [017-v17-workflow-and-live-readiness.md](017-v17-workflow-and-live-readiness.md) | v17 | 跨模块回归、账户到推荐、实机前置、MySQL授权、媒体许可 | 活跃 | 验证、前后端联调、数据库、媒体 |
| [018-v18-local-backend-start-authorization.md](018-v18-local-backend-start-authorization.md) | v18 | 后端启动授权、专用账户、隐藏输入、凭据缺失、安全入口 | 活跃 | 本机开发、数据库、验证 |
| [019-v19-user-local-backend-running.md](019-v19-user-local-backend-running.md) | v19 | 用户本机建库、初始迁移、管理员、后端启动、前端待启动 | 活跃 | 本机开发、数据库、前后端联调 |
| [020-v20-admin-origin-and-interface.md](020-v20-admin-origin-and-interface.md) | v20 | CSRF来源、5173代理、静态资源、后台界面、登录 | 活跃 | 配置、管理后台、验证 |
| [021-v21-desktop-layout-and-material-audit.md](021-v21-desktop-layout-and-material-audit.md) | v21 | 后台桌面600px、样式优先级、MP3素材清单、未导入 | 活跃 | 管理后台、媒体、验证 |
| [022-v22-local-metadata-and-draft-import.md](022-v22-local-metadata-and-draft-import.md) | v22 | 元信息、44首时长、候选标签、40首草稿导入入口 | 活跃 | 曲库、标签、管理后台、验证 |
| [023-v23-local-draft-audio-binding.md](023-v23-local-draft-audio-binding.md) | v23 | 本机音频、批量关联、指纹核验、草稿试听、逐首事务 | 活跃 | 曲库、媒体、管理后台、验证 |
| [024-v24-readable-tags-and-library.md](024-v24-readable-tags-and-library.md) | v24 | Tag object、中文分组、70项词表、标签说明、草稿保存 | 活跃 | 标签、曲库、管理后台、验证 |
| [025-v25-admin-select-text-clipping.md](025-v25-admin-select-text-clipping.md) | v25 | 标签文字裁切、select高度、内边距、CSS缓存更新 | 活跃 | 管理后台、标签、验证 |
| [026-v26-remove-admin-source-license-form.md](026-v26-remove-admin-source-license-form.md) | v26 | 移除来源许可表单、简化上架、历史信息保留、试听校验 | 活跃 | 管理后台、媒体、验证 |
| [027-v27-publish-button-and-tag-crud.md](027-v27-publish-button-and-tag-crud.md) | v27 | 一键发布、下架、标签CRUD、删除确认、关联管理 | 活跃 | 管理后台、标签、媒体、验证 |
| [028-v28-pagination-selected-colors.md](028-v28-pagination-selected-colors.md) | v28 | 分页、当前页深色、未选浅色、样式缓存 | 活跃 | 管理后台、验证 |
| [029-v29-song-tag-duplicate-validation.md](029-v29-song-tag-duplicate-validation.md) | v29 | 标签重复、MySQL1062、保存前校验、删除更新顺序 | 活跃 | 曲库、标签、管理后台、验证 |
| [030-v30-registration-validation-feedback.md](030-v30-registration-validation-feedback.md) | v30 | 注册、密码规则、字段提示、前置校验 | 活跃 | 前端、账户、验证 |
| [031-v31-continuous-indices-and-ten-daily.md](031-v31-continuous-indices-and-ten-daily.md) | v31 | 连续序号、第二页21、每日10首、旧快照兼容 | 活跃 | 前端、推荐、验证 |
| [032-v32-favorite-hearts-stable-list.md](032-v32-favorite-hearts-stable-list.md) | v32 | 收藏爱心、原位反馈、推荐不移除、状态读取 | 活跃 | 前端、收藏、推荐、验证 |
| [033-v33-admin-recommendation-diagnostics.md](033-v33-admin-recommendation-diagnostics.md) | v33 | 管理员诊断、双路分数、权重、邻居、只读试算 | 活跃 | 推荐、管理后台、验证 |
| [034-v34-compact-desktop-layout.md](034-v34-compact-desktop-layout.md) | v34 | 桌面紧凑布局、简介横栏、歌曲密度、手机适配 | 活跃 | 前端、页面、验证 |
| [035-v35-stable-favorites-and-playback-modes.md](035-v35-stable-favorites-and-playback-modes.md) | v35 | 快照收藏保留、播放队列、四种模式、上一首下一首 | 活跃 | 前端、推荐、播放器、验证 |
| [036-v36-rating-module.md](036-v36-rating-module.md) | v36 | 评分实体、1—5分接口、原位评分控件、反馈矩阵准备 | 已实现 | 用户、曲库、推荐、前端、验证 |
| [037-v37-feedback-matrix-and-tfidf.md](037-v37-feedback-matrix-and-tfidf.md) | v37 | 反馈矩阵、评分映射、标签级TF-IDF、内容画像、低分排除 | 已实现 | 推荐、评分、行为、标签、验证 |
| [038-v38-item-cf-independent.md](038-v38-item-cf-independent.md) | v38 | Item-CF、歌曲相似度、余弦相似度、相似歌曲召回、独立实现 | 已实现 | 推荐、反馈矩阵、验证 |
| [039-v39-three-route-fusion.md](039-v39-three-route-fusion.md) | v39 | 三路融合、有效权重、User-CF、Item-CF、诊断、旧快照兼容 | 已实现 | 推荐、每日推荐、诊断、验证 |
| [040-v40-scene-and-time-weights.md](040-v40-scene-and-time-weights.md) | v40 | 场景选择、上海时区、动态权重、推荐解释、快照上下文 | 已实现 | 推荐、每日推荐、前端、诊断、验证 |
| [041-v41-offline-evaluation-pipeline.md](041-v41-offline-evaluation-pipeline.md) | v41 | 时间切分、五组方法、分类指标、多样性、新颖性、冷启动分组、实验清单 | 已实现 | 离线评价、推荐、论文实验 |
| [042-v42-visualization-dashboard.md](042-v42-visualization-dashboard.md) | v42 | 实验看板、用户偏好、推荐路由、指标对比、模拟数据标识 | 已实现 | 前端、实验评价、论文展示 |
| [043-v43-simulated-live-acceptance.md](043-v43-simulated-live-acceptance.md) | v43 | 阶段9、模拟联调、真实数据切换、证据边界 | 已实现 | 业务联调、推荐、播放、实验、论文 |
| [044-v44-simulated-user-seeding.md](044-v44-simulated-user-seeding.md) | v44 | 模拟用户、行为生成、幂等导入、离线评价、来源隔离 | 已实现 | 曲库、行为、评分、推荐、实验 |
| [045-v45-tag-and-catalog-replan.md](045-v45-tag-and-catalog-replan.md) | v45 | 标签重构、时间上下文、自动导入、自动标注、阶段暂停 | 计划 | 标签、推荐、曲库、媒体、实验 |
| [046-v46-formal-tag-vocabulary-and-compatibility.md](046-v46-formal-tag-vocabulary-and-compatibility.md) | v46 | 53项正式词库、扩展场景映射、旧候选兼容、A1专项验证 | 已实现 | 标签、曲库、验证 |
| [047-v47-a2-tag-constraints-and-ncf-hook.md](047-v47-a2-tag-constraints-and-ncf-hook.md) | v47 | A2标签数量约束、ncf_score与ncf零权重预留 | 已实现 | 标签、推荐、诊断、验证 |
| [048-v48-eight-time-context.md](048-v48-eight-time-context.md) | v48 | A3八档时间上下文、场景映射、动态权重、零迁移 | 已实现 | 推荐、场景、时间上下文、验证 |
| [049-v49-batch-local-audio-import.md](049-v49-batch-local-audio-import.md) | v49 | B1三格式扫描、私有批次、指纹去重、草稿媒体导入与重试 | 已实现，实机待验 | 曲库、媒体、后台、验证 |
| [050-v50-auto-tag-candidates.md](050-v50-auto-tag-candidates.md) | v50 | B2元数据/声学规则候选、证据、阈值和可选写入 | 基础实现，解码与质量待验 | 标签、曲库、音频、验证 |
| [051-v51-local-ffmpeg-validation.md](051-v51-local-ffmpeg-validation.md) | v51 | 复用本机FFmpeg、环境配置、40首只读分析与覆盖边界 | 解码已验证，标签质量待验 | 启动、音频、标签、验证 |
| [052-v52-clap-isolated-installation.md](052-v52-clap-isolated-installation.md) | v52 | CLAP隔离CPU环境、官方权重校验、三首片段推理 | 安装通过，业务接入待做 | 模型、标签、环境、验证 |
| [053-v53-project-local-model-storage.md](053-v53-project-local-model-storage.md) | v53 | 模型移入local-ai、Git忽略、默认路径及离线复验 | 已完成 | 模型、存储、验证 |
| [054-v54-clap-multisegment-batch-candidates.md](054-v54-clap-multisegment-batch-candidates.md) | v54 | CLAP多片段、19类映射、拒识及批次候选入口 | 功能完成，质量待验 | 模型、标签、后台、验证 |
| [055-v55-full-catalog-clap-diagnosis.md](055-v55-full-catalog-clap-diagnosis.md) | v55 | 40首120片段只读诊断、拒识分解、描述敏感性 | 诊断完成，优化待做 | 模型、标签、诊断 |
| [056-v56-clap-prompt-comparison.md](056-v56-clap-prompt-comparison.md) | v56 | 曲风描述受控对照、原基线复现、候选集中与不切换生产 | 对照完成，质量待验 | 模型、描述、诊断 |
| [057-v57-clap-sampling-comparison.md](057-v57-clap-sampling-comparison.md) | v57 | 原首中尾与内部取样配对、复现对照、质量边界 | 对照完成，质量待验 | 模型、取样、诊断 |
| [058-v58-clap-reference-foundation.md](058-v58-clap-reference-foundation.md) | v58 | 12首参考包、40首元数据审计、证据门禁 | 工具完成，参考证据待核实 | 模型、参考集、评价 |
| [059-v59-multilabel-offline-pilot.md](059-v59-multilabel-offline-pilot.md) | v59 | 同15首多标签试验、2/3/2上限、偏置未解决不切生产 | 试验完成，质量未过 | 模型、多标签、拒识 |
| [060-v60-minimum-label-offline.md](060-v60-minimum-label-offline.md) | v60 | 用户初步认可、剩余25首1—2/1—3/1—2及低把握补位 | 离线完成，待试听 | 多标签、补位、场景 |
| [061-v61-existing40-retag-entry.md](061-v61-existing40-retag-entry.md) | v61 | 40首统一清单、指纹匹配、备份事务更新入口 | 入口完成，真实写入待本机凭证 | B3、重标、备份 |
| [062-v62-retag-match-diagnostics.md](062-v62-retag-match-diagnostics.md) | v62 | 匹配失败只读诊断与缺失/重复明细 | 入口完成，待本机查询 | B3、匹配、诊断 |
| [063-v63-library40-plan-correction.md](063-v63-library40-plan-correction.md) | v63 | 36相同+库内4首补分析、新计划显式选择 | 清单修正完成，待本机写入 | B3、曲库、精确匹配 |
| [064-v64-batch-multilabel-preview-save.md](064-v64-batch-multilabel-preview-save.md) | v64 | 三类预览、显式确认新草稿写入、2/3/2发布校验 | 子任务完成，B3待续 | 后台、批量、多标签 |
| [065-v65-one-click-batch-tagging.md](065-v65-one-click-batch-tagging.md) | v65 | 单表选曲/全选、一键分组、进度与停止 | 功能完成，视觉待验 | B3、交互、批量 |
| [066-v66-batch-request-target-fix.md](066-v66-batch-request-target-fix.md) | v66 | 修复具名action遮蔽地址、非JSON分类提示及回归 | 代码修复，实机待验 | B3、请求、表单 |
| [067-v67-batch-publish.md](067-v67-batch-publish.md) | v67 | 草稿全选发布、逐首校验、失败保留、日志与幂等 | 实现完成，实机待验 | B3、发布、后台 |
| [068-v68-direct-import-publish.md](068-v68-direct-import-publish.md) | v68 | 同页导入发布、可选草稿及最近批次恢复 | 实现完成，实机待验 | B3、导入、简化 |
| [069-published-song-list.md](069-published-song-list.md) | v69 | 已发布歌曲清单、标签/播放状态/时间及多入口 | 实现完成，真实库待核对 | B3、发布、核对 |
| [070-admin-dashboard-shortcuts.md](070-admin-dashboard-shortcuts.md) | v70 | 首页快捷入口、Group过滤、授权卡紧凑布局 | 实现完成，视觉待验 | B3、后台首页、布局 |
| [071-local-secret-and-session-persistence.md](071-local-secret-and-session-persistence.md) | v71 | 本机密码文件及持久会话密钥 | 启动入口已实现 | 本机、登录 |
| [072-batch-candidate-editing.md](072-batch-candidate-editing.md) | v72 | 批次三类候选编辑、人工来源及导入复核 | 实现完成，实机待验 | B3、标签、候选 |
| [073-c1-formal-simulation-foundation.md](073-c1-formal-simulation-foundation.md) | v73 | C1只读盘点、新标签画像与八时段生成 | 基础完成，真实生成待字典补齐 | C1、模拟、时段 |
| [074-c1-live-simulation-applied.md](074-c1-live-simulation-applied.md) | v74 | 真实库补30标签与200模拟账号、保护数据复核 | C1数据准备完成 | C1、MySQL、三路 |
| [075-c2-six-method-simulated-evaluation.md](075-c2-six-method-simulated-evaluation.md) | v75 | 六方法实际模拟对比、八时段敏感性与看板 | 本批完成，冷启动效果未测 | C2、实验、看板 |
| [079-v079-song-detail-sharing.md](079-v079-song-detail-sharing.md) | v079 | 歌曲详情、复制链接、分享、窄屏P2关闭、13项、PASS WITH KNOWN RISKS、#008 | 实现与离线复核闭环，真实剪贴板/手机视觉/手动选中待验 | 分享、详情页、链接 |
| [078-v078-personal-center-history.md](078-v078-personal-center-history.md) | v078 | 个人中心、history、PLAY去重、P2关闭、85项、PASS WITH KNOWN RISKS、#008 | 实现与离线复核闭环，浏览器/视觉/真实试听待验，非完整业务验收 | 个人中心、历史、收藏、兴趣 |
| [080-v080-song-comments.md](080-v080-song-comments.md) | v080 | #008评论、双PROTECT、0004新表、20/84 | 实现与离线复核历史；部署状态另见081 | 评论、权限、异步 |
| [081-v081-song-comments-deployment.md](081-v081-song-comments-deployment.md) | v081 | #008评论部署、0004_comment、19文件、备份、17表一致、20/84、74992、保留Comment回退 | 据执行者报告部署子项闭环；独立部署复核PASS WITH KNOWN RISKS（据主任务转交的独立代理最终报告，未重跑数据库/专项），实机待用户 | 评论、迁移、部署、回退 |
| [082-v082-social-follow-deployment.md](082-v082-social-follow-deployment.md) | v082 | #008关注/粉丝/主页、0005_follow、26文件、449/191、真实库回滚验证、77148 | 部署子项闭环，浏览器/手机/真实会话待用户验收，#008未关闭 | 关注、主页、迁移、部署 |
| [083-v083-d1-real-acceptance.md](083-v083-d1-real-acceptance.md) | v083 | #007 D1只读验收、MySQL 9.2.0/22表/无待迁移、40音频可达、标签2-3-2违规0、三路诊断可算、5批次 | 只读子项闭环；前台浏览器、授权确认与实机待用户 | 标签体系、D1、真实库、验收 |
| [084-v084-ncf-four-route-simulation.md](084-v084-ncf-four-route-simulation.md) | v084 | 模拟数据下NCF第四路最小确定性实现、四路融合与降级测试 | 45项推荐专项通过；论文仅可表述为模拟机制验证 | NCF、四路融合、D2、模拟实验 |
