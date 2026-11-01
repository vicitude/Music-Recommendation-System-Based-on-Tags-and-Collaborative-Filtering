# 媒体管理与受控播放验证记录

日期：2026-10-30。关联排期清单#003、#004。代码：backend/music/media.py、forms.py、admin.py、test_media.py及streamSong路由。契约见service-contracts.md“媒体实施边界”和completion-contract.md第2节。

## 已实现

- streamSong已接通，24/24个OpenAPI操作均有实现与路由；不等于完整CT-M-001或系统验收通过。
- 管理表单校验WAV/MP3/OGG实际字节、30MiB上限、扩展/MIME一致、WAV时长与截断、来源/许可字段和人工核验时间。album与attribution_text允许为空，与既定实体默认空字符串一致。
- 发布必须显式人工确认许可、允许播放、有效文件与核验时间；MP3/OGG必须先上传草稿，再用管理员受控audio预览实际收听并确认。结构检查不证明完整解码；checked_at不会自动生成。
- 服务端生成uuid文件名，媒体根内独占创建，不覆盖原文件；替换旧文件保留，数据库失败仅记录孤立新文件、不自动删除。
- Song/Tag通过Django admin维护，file_path只读，SongTag权重固定1。删除入口关闭，避免删除历史曲目/标签；普通账户与缺少模型权限的staff不能上传或预览。
- 用户播放依次检查登录、歌曲发布、许可/核验、文件后才解析Range；支持完整200及单段206，非法/多段/不可满足416，416无JSON/音频体。指定区间迭代输出，响应结束释放句柄，private,no-store且nosniff。
- 草稿预览仅管理员模型权限入口可用，不增加公开上传/预览API；/media路径未作为静态目录公开。

## 实测结果

| 检查 | 结果 | 边界 |
|---|---|---|
| 媒体专项测试 | 40/40通过 | 内存合成音频、SQLite与模拟文件系统，不写真实音频文件 |
| 全量后端回归 | 177/177通过 | 基础27 + 算法33 + 每日37 + 行为40 + 媒体40 |
| Django system check | 通过 | 包括管理页面配置 |
| makemigrations --check --dry-run | No changes detected | 无模型/迁移变更，不操作MySQL |
| 规格门禁 | 通过，4项自测通过 | 文档与已安装依赖一致性 |

覆盖WAV PCM参数/帧数/声明长度/时长、MPEG帧头与ID3边界、OGG版本/BOS/首页面边界、30MiB和+1字节、32种发布条件组合、MP3/OGG草稿/预览强制流程、表单MIME和来源校验、原路径不可伪造、独占uuid存储、根外拒绝、权限、管理员页面实际HTML响应、文件不公开直出、孤立文件日志、Range各分支、授权先于Range、注销阻断新请求和句柄释放。

TC-M-004/017/018已有对应后端测试；PT-M-009仅32组条件与本记录列出的边界通过，不称完整生成空间已穷尽。后台HTML响应测试不是浏览器实际解码预览。所有文件打开/存储均由BytesIO或模拟替代，既未核验真实磁盘存储竞态，也未播放用户素材；MySQL并发、浏览器、音频版权和研究效果仍无完成结论。

## 复核命令

从项目根目录执行：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music.test_media --settings=config.test_settings --verbosity=2
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
& '.\.venv\Scripts\python.exe' -B backend/manage.py check --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -B backend/manage.py makemigrations --check --dry-run --settings=config.test_settings
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

没有新增依赖、创建/删除临时音频、读取用户素材、连接MySQL、修改既有数据或Git操作。用户目录song/midi没有被导入；提供路径不等于授权发布。

## 下一阶段

前端实现登录/注册、兴趣、发现/收藏/歌单、每日推荐与单播放器，对接真实API并验证本地文件不上传、暂停/拖动不累计、事件同ID重试和刷新倒计时。之后在账户/库操作和素材发布证据具备时再做MySQL实机、授权音频浏览器预览/播放、Gherkin/完整CT/PT、性能与研究实验。
