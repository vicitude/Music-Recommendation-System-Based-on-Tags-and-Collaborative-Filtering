# 实施收尾规则

状态：提议，等待一次性实施批准。本文是spec.md第2、4、5、6、8部分的规范性补充；同主题旧摘要与本文冲突时，本文的显式规则优先，不自动改变既有业务范围。

## 1. 错误与输入

error-catalog.json是错误message、允许状态与details字段白名单的唯一源。公开API所有错误均返回error_code、message、details、request_id；details排序、去重且只含白名单字段，不含用户输入值。未分类错误使用INTERNAL_ERROR并回滚事务；日志记录内部异常但不返回堆栈。ApiError只接受字典中的错误码，未知码属于开发错误，不向客户端回显。

格式顺序：请求ID和统一now → 写请求CSRF → 登录会话（仅保护接口） → Content-Type → JSON语法/字段/类型 → 对象所有权 → 对象状态 → 业务限制 → 事务写入。405是路由层拒绝方法，不执行视图；415是写接口接收到非application/json请求体（admin上传除外）。空体仅允许OpenAPI没有requestBody的端点；有requestBody端点空体400，body上限64KiB，超出400且details=["request"]。不新增413错误码。bool不是integer，null只在Schema列出时接受，未知字段400。字符串先trim再校验，密码不trim；username先trim转小写再按正则校验。API原始username Schema描述的是规范化后值，客户端不能依赖大小写保存。

接口运行必须保持OpenAPI成功与业务错误响应；405、415为全局路由/解析错误，以本规则为准。416媒体Range仍使用无JSON体的HTTP规范分支。登录失败、注销和账户停用遵循原会话规则，停用账户返回AUTH_REQUIRED。

## 2. 管理上传与媒体

上传仅使用Django admin multipart表单，不新增公开上传API。SongAdminForm使用upload作为非模型FileField(required=False)，管理员不得直接填写file_path；file_path只读，clean_file_path签名保留并验证原存储值。新歌曲可保存草稿但发布必须有文件；已有文件且未选择upload时保留原文件。upload=空文件拒绝，最大31457280字节，超出拒绝。一个表单最多1个文件；上传到服务器前后都不凭客户端content_type决定真实类型。

允许扩展.mp3/.wav/.ogg（大小写归一）；扩展与检测MIME必须相符。文件名由服务器uuid4().hex加归一扩展构成，相对目录songs/，不保留原文件名；解析后的绝对路径必须仍在MEDIA_ROOT内。检查路径分段、符号链接最终路径，拒绝媒体根外结果；不解压、不执行、不从外部URL下载。media不可作为静态公开目录直出，受权限stream视图提供内容。

头检测规则：WAV要求前12字节RIFF、长度字段与WAVE标识，使用Python标准库wave读取非压缩PCM、声道1或2、采样宽度1—4字节、采样率8000—192000Hz，拒绝解析失败与0帧；duration_ms取ceil(1000*nframes/framerate)，并顺序读取声明帧数检查截断。OGG要求OggS及版本字节0、首个page标识beginning-of-stream；MP3要求有效ID3v2长度界定后出现合法MPEG音频帧头，或首帧直接合法；检查同步11位、版本非保留、layer非0、码率索引非0/15、采样索引非3。无法定位首帧拒绝，不凭ID3三个字节直接接受。

本版不新增ffmpeg或解码依赖。MP3/OGG上述结构检查不证明全文件可解码：管理员必须在浏览器音频预览得到有限且大于0的duration、无error并实际播放至少min(5秒,时长)后人工核验，填写duration_ms与checked_at再发布；该确认由管理员负责，不信任前端声明为算法证据。WAV计算时长与输入duration_ms差异>1000ms时拒绝；MP3/OGG输入取预览时长ceil到毫秒。研究报告不宣称服务器完整解码检测。浏览器不支持的音频留草稿或转用授权WAV，不安装转换器。

验证后才写文件，写入后数据库保存失败时记录孤立文件到日志、不自动删除；替换文件时旧文件保留、不覆盖、不自动清理，删除授权单独申请。不会通过迁移或测试删除用户既有媒体。上传中的媒体与正式记录均不包含真实许可证密钥。来源source_url、license_url仅允许http/https且不由后端自动访问；许可人工审查不得只靠网址存在。

媒体测试编号TC-M-017：空文件、超限、扩展冲突、截断WAV、媒体根外路径均拒绝发布。TC-M-018：MP3/OGG结构检查通过但无预览核验时不能发布。发布布尔字段active和checked_at由管理表单状态控制，普通用户不可写。全表单错误使用Django表单ValidationError，API错误字典只约束公开JSON接口，不强行给admin页面返回JSON。

## 3. 页面与前端契约

页面路由、组件文件、权限、API动作以frontend-contract.json为准。只使用已安装Vue、Element Plus和原生fetch，不新增router/store依赖；hash路由使用location.hash、hashchange与导航函数navigate(path:string):void，hash路径限定声明模板，未知路径显示404页。页面中所有业务文本中文，用户输入使用文本渲染，禁止v-html。请求的公共模块文件frontend/src/api/client.ts。

request<T>(path:string,init:RequestInit={}):Promise<T>使用同源/api/v1、credentials=same-origin，写请求带X-CSRFToken；启动与每次登录后重新读取csrf接口。204返回undefined；错误抛ApiError{error_code,message,details,request_id}，网络失败抛error_code=NETWORK_ERROR的本地展示错误，不伪装为后端业务错误。401清理内存用户并导航登录；403 CSRF_FAILED只允许重新取token后提示用户手工重试，不自动重复写入。表单提交期间禁用重复操作，最终状态由服务器结果决定，不乐观增加收藏。

会话仅用服务端Cookie，不写localStorage身份或令牌。GET允许用户点重试；普通写操作不自动重试，只有播放事件按既有同event_id重试规则执行。加载、空列表、错误和无权限四种UI状态都需可观测。登录后由onboarding_completed决定进入引导或推荐页。登录页不给定默认密码；管理账号仅在实施授权后通过createsuperuser交互生成，凭据不落文档。

播放器文件frontend/src/components/AudioPlayer.vue，只有一个全局HTMLAudioElement；公开方法playSong(song:Song):Promise<void>、selectLocal(file:File):void、pause():void、seek(positionMs:number):void。被浏览器拒绝自动播放时提示点击播放，不连发PLAY；切歌先终止旧会话再初始化新会话。来自本地File只用对象URL、不上传、不产生曲库训练事件。进度拖动只更新currentTime，不累计listened_ms。每次有效playing周期使用performance.now增量累加，在pause/waiting/seeking/ended前冻结；超出duration的累计服务端仍按duration限幅。媒体失败提示且不补造COMPLETE。

收藏与歌单列表禁用已下架对象播放；每日推荐解释原样文本展示，不重写证据。刷新按钮根据next_refresh_at倒计时，429使用Retry-After修正；空结果展示empty_reason对应中文文案。服务端过滤后的推荐rank作为展示顺序，不自行排序。管理员入口链接/admin/，不另建Vue管理后台。

页面级验收TC-M-019：401跳转、表单失败恢复、空列表、刷新限流倒计时。TC-M-020：本地文件不产生上传/行为请求，暂停与拖动不增加收听累计。业务实现后使用Django API测试加本地浏览器验收，不自动安装浏览器测试框架。

## 4. 环境与阶段边界

本次只增加文档和本地检查脚本。真实CI配置提供手动触发模板，不初始化Git、不推送、不触发云任务；配置文件存在不能宣称远程CI跑过。未选的path-align、verify-matrix、drift-inventory仍保持关闭。

文档门禁现在可执行且必须通过；后端、前端、验收门禁是对未来实现的精确命令，缺少实现时必须退出2，不标记为跳过通过。真正业务TC/PT只能在实现后按阶段运行；不能用“尚无业务”否定规格已经准备好，也不能反过来把准备好写成系统验收完成。

无数据库授权可先实现纯算法和前端类型文件，但不能用SQLite结果冒充MySQL兼容。实际联调只使用用户专用项目库，默认库名music_recommender_dev，测试库music_recommender_test；两个名字需要在集中授权时确认。已有MySQL9.2保持原样，兼容测试失败时停止并报告，不自动降级或另建实例。
