# v66 一键打标请求地址与错误提示修复

## 来源与范围
对应BACKLOG #007。用户反馈重新登录后仍出现Unexpected token '<'，截图证明收到非JSON响应，但不足以判断是登录失效、旧进程、CSRF或服务器错误。此前将HTML一概归因旧后端的说明不成立。

## 原因与处理
模板分析表单含name=action字段，浏览器具名控件会遮蔽HTMLFormElement.action；脚本原来fetch(form.action || window.location.href)可能把字段元素当地址。原最小DOM测试把form.action设为字符串，未覆盖实际表单行为。

改用form.getAttribute('action') || window.location.href，既支持显式地址，又保留当前批次查询参数。测试将form.action模拟为控件，并断言每次实际请求目标；原5/5/2、停止及不重试断言保留。脚本静态版本更新为20261109-2。

非JSON按登录地址、HTTP403、5xx和其他状态分类，不将所有跳转当登录；详细原因显示在总体状态处，超时明确提示。不输出服务器HTML，不关闭CSRF，不自动重发或改变候选保存逻辑。

## 验证及边界
- node --test tools/test_batch_import_ui.cjs：12项通过。
- config.test_settings下music.test_minimum_candidates：7项通过，SQLite内存，不是MySQL或真实模型验收。
- verify_spec.py --self-test --check-environment：4项自测、文档及环境门禁通过。
- 浏览器与子代理入口返回unsupported，未做浏览器请求/视觉验证或独立复核；不能声称已从实际网络记录确认截图唯一成因。
- 未写真实库、批次或音频，无新依赖/迁移/模型下载；此前全后端376项本轮未重跑。

## 后续验收
用户Ctrl+F5刷新后先选1首测试；若仍失败，收集新总体HTTP提示和后端同期异常。现有40首正式标签不变，不要求重新导入。
