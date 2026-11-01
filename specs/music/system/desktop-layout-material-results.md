# 桌面后台宽度修复与候选歌曲检查

日期：2026-10-30。用户提供后台桌面截图并请求导入D:/AAA素材库/song。

## 桌面布局

截图呈现大屏后台内容仅占左侧，不是预期手机布局。定位Django内置base.css的`.dashboard #content { width: 600px; }`仍生效，新版模板保留dashboard类但未覆盖该选择器。原有`#content`仅定义padding，无法覆盖固定宽度，是本轮根因。

修复限定music-dashboard：内容width:100%、max-width:1680px、box-sizing:border-box、水平居中，父flex和grid项min-width:0。桌面内容+指南两栏，中屏指南下移，手机单栏。登录页双栏布局不受此规则影响。样式URL增加版本参数v=20261030-2。没有修改Django包文件、不新增UI框架或外部资源。

新增ADM-M-009/010验证精确宽度选择器、断点存在、样式位于框架base/responsive之后及版本参数。后台10项定向、后端203项全量通过；文档门禁及4项自测通过。CSS检查不是浏览器像素/布局实测；受支持浏览器入口仍返回unsupported call，未建立浏览器会话，也未改走其他通道。不能声称截图复验已通过。

用户可先在后台Ctrl+F5强制刷新。若未更新，在用户后端窗口停止再运行既有start_local.py（不要--create-admin），重新登录刷新；后端--noreload不会自动重载Python配置，模板也可能已缓存。不更改账号或数据库内容。

## 外部素材只读检查

只读核对目录直接子文件，未递归读取IDE/下载器缓存，未读取歌词正文；结果见[material-audit.json](material-audit.json)。90个直接文件中：MP3 44、FLAC 2、M4A 1、MP4 2、LRC 41。

- 44首MP3均在既有大小范围内，通过inspect_audio基础结构检查，并记录SHA256。
- 2个FLAC、1个M4A、2个MP4不在当前WAV/MP3/OGG支持范围，未转换或引入依赖。
- MP3结构检查不是完整帧/浏览器解码，既有检测器不计算MP3时长；清单duration_ms=null，不写入1毫秒等占位数据，不按文件大小猜时长。
- 所有许可保持UNVERIFIED，source_url/license_evidence不伪造；下载路径和歌词不能证明系统内播放授权。未根据文件名猜风格/情绪/场景标签。
- imported_count=0；本轮没有复制/移动/修改源音频、写数据库、转码、上传或发布。两项服务8000/5173在检查时均监听，未重启/终止用户服务，未读取凭据。

本轮没有实现或执行批量导入器，不把只读清单叫作入库。下一步用户确认用于该项目的播放许可及必要来源证据后，才能准备受控草稿导入与时长/实际预览，不绕过既有发布校验。未确认许可时继续保留候选清单，用户可使用现有单播放器主动选择本地文件、不上传，不混入线上推荐或论文实验。

复核：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music.test_admin_ui --settings=config.test_settings --verbosity=1
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

前端源码/依赖及后端模型未变；本轮不重复前端测试/构建，最近结果为前端47项及构建通过。没有安装依赖、迁移、删除文件、Git操作或写入真实密码。
