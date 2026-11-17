# AI 摘要链路（2026-11-17）

## 已实现范围

全国服务增加独立 `summary` 进程。每 15 秒扫描已发布的当前版本，每批最多 100 篇，按发布日期从新到旧建立持久任务；新近收录的版本优先。采集器仅领取 list/detail/attachment，摘要器仅领取 summary，摘要不挂接 CollectionRun，不影响采集成功时间。内容版本、输入 SHA、模型与提示词版本构成任务去重键；相同内容不重复生成，过时版本任务跳过。进程崩溃后租约过期可恢复，已落库成功结果不再次请求模型。

正文足够时使用已存正文；正文不足时使用已提取附件文字，记录附件名称、URL 和页码等定位信息。图片、视频或正文不足时不编造摘要。等待附件的版本在附件完成/失败时重新进入判断。每次输入最多 24,000 字符、附件最多 100 个文本块；截断会明确展示“未覆盖全文/完整附件”。这是正文或可读附件的摘要，不代表整份官网材料的所有附件均已识别。

每次生成 1–3 条要点，全部经过 JSON 结构、非空内容、长度、来源编号、原文连续引句和偏移位置校验；任意一条不通过，整次结果不发布。原文视为不可信资料，不执行其中指令。**逐字引句校验能够确认引用存在，不能保证模型概括在语义上绝对无误**，界面保留“辅助摘要 · 以原文为准”。AI 不覆盖现有自动/人工分类。

HTTP 超时、错误格式、引句错误等最多自动尝试 3 次，指数退避。429、网络和服务端异常会进入服务级冷却；认证错误暂停至少 10 分钟、余额不足暂停 1 小时。日志/任务只存固定错误码，不存密钥、提示词或服务商响应原文。任务耗尽后保留失败状态，可经管理员接口或 CLI 有界重试。SummaryRecord 与 Audit 保存输入 SHA、模型、提示词版本、范围、生成时间和 token 用量。

## 小程序

列表保留首条摘要预览；详情展示 AI 要点，每条可展开/收起原文引句。区分待生成、排队、生成中、自动重试、服务暂不可用、失败、未配置、等待附件和文字不足。刷新只读取状态，不允许公开接口反复触发付费生成。活跃详情最多每 8 秒轮询一次、最多 12 次；离开或隐藏页面停止轮询，失败保留已显示内容。

## 配置和运行

本地全国服务私有文件：`.runtime/national-service/ai.env`（被 Git 忽略；建议权限 600）。

```dotenv
POLICY_AI_KEY=填写已有密钥
POLICY_AI_URL=https://api.deepseek.com/v1/chat/completions
POLICY_AI_MODEL=deepseek-chat
POLICY_AI_TIMEOUT=90
POLICY_AI_INTERVAL_SECONDS=3
POLICY_AI_BATCH_SIZE=100
```

只支持 HTTPS，不跟随跳转携带凭证。摘要 worker 每 15 秒重新读配置，API 按请求读取 AI 配置；不改变既有数据库位置。没有密钥时不会发请求或消耗任务重试次数，页面展示未配置。

```bash
# 启动本机登录自启服务（API、采集器、摘要器）
python3 scripts/manage_national_service.py install --root .runtime/national-service
# Linux/独立进程部署
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service summary --root .runtime/national-service
# 查看真实进度，无密钥输出
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service summary-report --root .runtime/national-service
# 可选立即建立历史任务；后台本身会持续批量建立
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service summary-backfill --root .runtime/national-service --limit 100
# 修复配置或故障后，有界重新尝试失败任务
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service summary-retry --root .runtime/national-service --limit 100
```

macOS 服务为 `com.weijianwei.national-summary`，日志 `/private/tmp/weijianwei-national-summary.log`。电脑休眠、关机或退出登录时后台不能继续工作；此实现尚未部署到腾讯云。已有三省观察服务独立运行。

## 验证与当前限制

- 后端最终完整回归已通过 404 项，包含恢复、附件唤醒、超时、引句偏移等摘要专项 20 项。
- 小程序 7 组自动测试通过，包含真实 FastAPI 契约、状态轮询、引句展开、刷新失败及页面退出清理。
- 微信开发者工具通过隔离样例 API 验证 ready/queued/generating/retrying/failed/waiting_content/insufficient_content 七种状态、真实点击引句展开收起及刷新；验收后恢复全国 API 地址。脚本 `scripts/serve_summary_ui_fixture.py`、`scripts/test_miniprogram_summaries.cjs`；截图位于 `.runtime/summary-*-fixture.png`。
- 当前私有 AI 配置仍为空：没有完成真实服务商调用，也没有将历史内容实际生成摘要；不能把模拟响应测试当作真实 AI 验收。
- 线上配置访问待恢复：浏览器控制工具在当前会话不可用，现有 SSH 密钥未获服务器授权。没有变更服务器认证或读取其他无关凭证。
