# 本地歌曲资料整理与草稿导入结果

后续状态：用户截图已显示后台歌曲资料记录，具体数量未复核；本文“未实际导入”等描述为v22时点记录。现已增加音频关联及后台试听入口，见[最新结果](local-audio-results.md)，本轮未实际执行音频复制/关联。

日期：2026-10-30。用户同意先处理44首MP3资料及候选标签。结果清单：[local-catalog.json](local-catalog.json)、[核对表](local-catalog-review.md)。

## 实际提取

使用Windows内置Shell媒体属性读取原文件，无新增依赖、无歌词读取或音频转码。44首均取得媒体时长，总计约149.1分钟；40首从内嵌属性取得标题及歌手，剩余4首只有文件名标题。SHA256去重未发现相同字节内容，不能据此排除不同编码的同一作品。

缺歌手的4首：爱人错过伴奏.MP3、精灵进化小曲.mp3、精卫.MP3、雨爱dj.mp3。保持歌手空白、禁止本次草稿导入，不从熟悉的歌名猜实际演唱者/混音版本。44首都有时长；Windows媒体属性时长不是完整解码或播放证明。

23首生成候选标签，其余21首无可靠候选而保留空白。标签来自显式歌曲常识映射或文件名版本词（钢琴版/伴奏/管弦乐/混音等），没有试听、声学模型或联网核验，全部needs_review=True。风格/情绪MEDIUM表示常识候选而非统计概率，版本词/场景LOW；场景是用途建议，不是客观曲目属性。所有候选可查看依据，不作为论文评价真值。

## 已实现的导入入口

http://127.0.0.1:5173/admin/music/song/local-import/

管理员登录后可从歌曲列表「导入本地歌曲资料」进入。预览44首，默认选中40首资料完整项；缺歌手的4项禁选。须勾选仅创建资料草稿，候选标签默认不应用；用户查看后可另勾选接受初步标注，再确认导入。

入口复用后台会话/权限/CSRF，固定读取项目内生成清单，不接收路径、不提取数据库密码或Cookie。事务内创建草稿，可选Tag/SongTag；同hash跳过，不覆盖已有人工修改。当前管理员行锁序列化相同管理员提交，未宣称不同管理员并发唯一约束已验证。

草稿active/playback_allowed/redistribution_allowed均False，checked_at=None，file_path/source_url/license_name/license_url空白。source_name记录LOCAL_DRAFT_SHA256指纹，署名说明记录资料和候选来源。只导入资料，不复制音频、不填许可、不发布；不会立即进入当前每日推荐。后续需完成标签校正、受控本地音频关联和既有播放发布条件。

## 验证与实际状态

- 新增LC-M-001至019共19项通过，后端全量222项通过。
- 实际清单44项与原只读音频指纹一致；内存SQLite整批创建40项及重复跳过40项测试通过，已验证失败回滚、非法清单、权限、CSRF、GET只读、草稿不泄漏公开曲库。
- makemigrations --check --dry-run未检测模型变更；离线文档门禁及4项自测通过。
- 没有安装依赖、创建迁移、读取密码、连接真实MySQL、写真实Song/Tag、复制音频、启动/终止用户服务、删除文件或Git操作。前端源码未变，不重复构建。
- 当前没有可调用的受支持浏览器执行入口，不能替用户在已登录页面点击；真实MySQL导入数量仍为未执行，不把测试40项写为实机入库成功。

## 用户启用步骤

在运行后端的窗口Ctrl+C停止，再执行下面命令；输入项目数据库密码即可，管理员已存在，不加--create-admin：

~~~powershell
& 'D:\SOLO\ddd\毕业设计\.venv\Scripts\python.exe' -B 'D:\SOLO\ddd\毕业设计\backend\start_local.py'
~~~

打开上述导入页，查看候选；确认草稿（以及需要时接受标签）后提交。成功返回歌曲列表，顶部显示新建/跳过数量。后台默认筛选全部歌曲；前台发现/推荐仍为空或不含草稿是正确行为。新页面404通常说明运行中的--noreload后端尚未重启，不重复建库建表。

复核：

~~~powershell
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music.test_local_catalog --settings=config.test_settings --verbosity=1
& '.\.venv\Scripts\python.exe' -B backend/manage.py test music --settings=config.test_settings --verbosity=1
& '.\.venv\Scripts\python.exe' -I -B specs/music/system/verify_spec.py --self-test --check-environment
~~~

prepare_local_catalog.py是开发期生成器：接收Windows属性JSON的UTF-8标准输入，只读源音频并输出apply_patch补丁，已有结果拒绝覆盖；不连接数据库。不作为用户必须执行步骤。
