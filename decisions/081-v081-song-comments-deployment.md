# 决策 081-v081-song-comments-deployment

> **状态**：据执行者报告，授权迁移与定点部署完成；独立部署复核待回传，实机待用户。
> **日期**：2026-11-11。
> **编号说明**：写入前核对源目标决策文件及索引，081均未占；源数字末项080，目标缺失080按源原文补入，不改原有编号。
> **补充**：080的真实部署与回退边界；源080历史正文不改。
> **局部闭环：排期清单 #008 评论部署子项**；不关闭整项，不代表完整业务验收。

## 0 · 一句话
用户明确授权后新增真实评论表、定点同步评论代码并重启本机后端，评论实机体验仍待用户验收。

## 1 · 事实与证据
- 【代码事实】授权依据：本次用户明确确认“新增music_comment、同步本阶段代码并重启后端”的会话指令。只项目账户127.0.0.1:3306 music_recommender_dev/music_recommender_app，不涉及其他库或真实测试评论。
- 【测试事实，据执行者报告及本会话执行输出】事前只读MigrationExecutor计划精确仅music.0004_comment正向，operations仅CreateModel Comment；源目标旧三迁移归一化内容一致（字节差异仅换行），无未登记评论表。先备份，再用源代码、目标venv及目标配置限定迁移，未先部署缺表代码。
- 【测试事实，据执行者报告及本会话执行输出】整库导出返回0、1,655,647字节、完成标记存在；备份15份原公开文件，清单登记4份新增文件。备份本地Git忽略保留，未输出SQL内容或持久化口令令牌，未验证恢复。
- 【测试事实，据执行者报告及本会话执行输出】迁移后music_comment为空；字段、双外键、索引、迁移记录及无待计划通过。原17表计数/摘要一致，既有权限不变，仅新增Comment内容类型1项、权限4项、迁移记录1项。
- 【测试事实，据执行者报告及本会话执行输出】目标19文件通过apply_patch定点同步，归一化内容一致，包含verification-contract.json和page-harness.mjs；目标后端20/20、前端84/84、typecheck及启动系统check通过。8000原PID72328变为74992；5173保留PID24152。
- 【代码事实】执行制品：目标local-ai/diagnostics/temp_comments_20261111-162237.json及本会话命令输出。本次归档未重新操作数据库或服务；独立部署复核报告尚未收到，不冒充独立结论。.agents缺失，不声称完整MAC流程或签名。

## 2 · 裁定
- 闭环#008评论授权迁移和定点部署子项，保留评论实机验收、关注/主页及联调，不整体关闭#008。
- 回退必须保留Comment模型、0004_comment迁移、music_comment表及数据，仅停用入口。直接退回不含Comment的旧models会被start_local表白名单拒绝，不采用此方案；不删表、不删评论、不逆迁移。
- 080保持原文，其未授权/未部署表述为历史时点，当前以081为准。

## 3 · 影响面
源D:/codex2/CFast/home/worktrees/c22d/毕业设计；目标D:/SOLO/ddd/毕业设计。仅第三阶段19文件，不覆盖目标独有D1/D2等变化，不改推荐算法或启动门禁。

| 类别 | 文件（相对项目根目录） |
|---|---|
| 后台7 | backend/music/models.py；backend/music/admin.py；backend/music/api/serializers.py；backend/music/api/views.py；backend/music/api/urls.py；backend/music/migrations/0004_comment.py；backend/music/test_comments.py |
| 规格5 | specs/music/system/api-bindings.json；specs/music/system/entities.schema.json；specs/music/system/migration-plan.json；specs/music/system/openapi.yaml；specs/music/system/verification-contract.json |
| 前端7 | frontend/src/api/client.ts；frontend/src/api/types.ts；frontend/src/components/SongComments.vue；frontend/src/pages/SongPage.vue；frontend/tests/client.test.mjs；frontend/tests/page-harness.mjs；frontend/tests/song-comments.test.mjs |

原17表迁移前后计数相同且摘要一致：music_user 203、music_song 40、music_tag 71、music_song_tag 212、music_user_tag 807、music_behavior 7662、music_favorite 2720、music_rating 2814、music_playlist 202、music_playlist_song 1603、music_recommendation_snapshot 9、django_admin_log 46、django_session 2、auth_group 0、auth_group_permissions 0、music_user_groups 0、music_user_user_permissions 0。不登记用户明细。

- 整库备份：D:/SOLO/ddd/毕业设计/local-ai/db-backups/comments-20261111-162237.sql。
- 公开文件备份：D:/SOLO/ddd/毕业设计/local-ai/sync-backups/comments-20261111-162237；manifest.json记录15份原文件/4份新增状态。
- 结构及完整部署结果：目标local-ai/diagnostics/temp_comments_20261111-162237.json。
- 启动日志：目标local-ai/diagnostics/temp_comments_backend_20261111-162237.log及同前缀.err.log；错误日志为空。临时辅助temp_comments_deploy.py保留，未经确认不删。制品均本地Git忽略，不含持久口令令牌。

## 4 · 门禁
**实际执行（2026-11-11，据执行者报告及本会话输出，非独立部署复核）**：

| 命令/操作 | 结果及范围 |
|---|---|
| 目标venv运行temp_comments_deploy.py preflight，源代码MigrationExecutor只读核验 | 精确单项正向CreateModel Comment，旧三迁移内容一致，无未登记评论表 |
| mysqldump.exe --host=127.0.0.1 --port=3306 --user=music_recommender_app --single-transaction --no-tablespaces --set-gtid-purged=OFF --result-file=<上述SQL路径> music_recommender_dev | 返回0，1,655,647字节且完成footer存在；MYSQL_PWD只在子进程环境，不在命令行，不输出SQL |
| temp_comments_deploy.py migrate内部call_command('migrate', 'music', '0004', interactive=False, verbosity=0) | 仅执行一次；结构/双FK/索引/迁移记录/空待计划通过，原17表计数摘要一致 |
| temp_comments_deploy.py sync逐文件apply_patch | 目标19文件归一化内容一致，15份原文件已备份，4份新增已记录 |
| 目标backend：test music.test_comments --settings=config.test_settings --noinput，目标venv通过execute_from_command_line执行 | 收集20、通过20、失败0，无收集错误；SQLite内存，不证明真实MySQL API交互 |
| 目标frontend：node --test tests/client.test.mjs tests/song-comments.test.mjs tests/song-share.test.mjs | 84通过，0失败/跳过/取消，无收集错误；含client27项，使用测试网络替身，非真实API探针 |
| 目标frontend：npm run typecheck | vue-tsc --noEmit通过 |
| 目标venv：backend/start_local.py --check-only | 系统check与专用库范围核验通过，未迁移/创建管理员 |
| 核验旧PID命令行及8000归属后只停72328；Start-Process -WindowStyle Hidden运行目标venv -u -B目标backend/start_local.py，定向日志 | 8000 PID74992监听，ExecutablePath D:/Python313/python.exe，CommandLine指向目标venv及start_local.py；无reloader，系统check通过；5173 PID24152不变 |

未执行：备份恢复演练、全量测试/构建、真实评论写入、浏览器/手机视觉及后台实机验收。本轮选择授权专项范围，未要求全量回归，但专项不替代全量/实机。此前5173 URL策略拒绝不重试、不绕过；无浏览器session或真实HTTP/API探针。

## 5 · 风险与已知边界
1. 专用库备份未做恢复验证，存在不等于可恢复；本地保留，由用户另行授权恢复演练，不承诺恢复结果。
2. 歌曲评论区/后台真实交互及手机视觉未验，由用户后续确认；当前只闭环部署，无真实评论/用户/兴趣测试写入，不宣称完整业务验收。
3. 旧models直接回退会被启动白名单拒绝；后续获授权回退仅关闭入口，保留Comment模型/迁移/表及数据，禁止删表逆迁移。
4. 独立部署复核待回传；本081先据执行者报告，不给出独立PASS结论，收到报告后按授权追加，080正文不改。
5. 旧前端大于500KB警告未在本轮重新构建验证，不扩展优化范围；Django为本机开发服务器，监听及系统check不代表生产部署或HTTP业务验收。

## 6 · 独立部署复核补充（2026-11-11）
本节据主任务转交的独立代理最终报告追加，归档者未重跑该复核；第1节、第5节“待回传”为报告收到前的历史状态，当前以本节为准。

**独立结论：PASS WITH KNOWN RISKS，可进入用户实机验收。** 仅关闭#008评论部署子项，不关闭整项，不等于HTTP或完整业务验收。

| 证据来源 | 已确认范围 | 未覆盖范围 |
|---|---|---|
| 独立部署复核（据主任务转交的独立代理最终报告） | 19/19文件归一化SHA256一致，各原始散列与部署记录匹配；8000 PID74992确认为目标启动入口、5173 PID24152监听；启动系统check无错误或Traceback、stderr为空；安全记录中的原17表计数与SHA256前后一致 | 未独立重跑数据库查询或专项测试；安全记录核对不等于重新连接真实库验证 |
| 执行者证据（独立未重跑） | 数据库已应用music.0004_comment、无待迁移、Comment为0；后端评论20/20、前端client/comments/share84/84、typecheck通过；备份导出及迁移结构检查见第4节 | 不冒充独立数据库或测试结果 |

恢复演练、真实HTTP、真实CSRF交互及DOM/手机验收未执行；无真实评论测试写入。下一步由用户实机验收。回退继续保留Comment模型、0004迁移和music_comment表及数据，仅停入口，不删表、不逆迁移；备份存在不代表恢复已验证。.agents缺失，不声称完整MAC或独立签名。
