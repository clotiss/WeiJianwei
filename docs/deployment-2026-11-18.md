# 2026-11-18 生产部署

用户授权将 V2 部署到腾讯云并替换线上代码，明确无需兼容旧业务。

## 已上线

- 广州轻量实例 `lhins-gxfnimwx`，域名 `https://wjwjwjw.top`。
- 2026-11-18 10:58（北京时间）切换 `nhc-api`，新版独立入口 `policy_v2.app:app`，Nginx 继续转发至 `127.0.0.1:8000`。
- `nhc-api`、`weijianwei-worker`、`weijianwei-summary` 均 active、enabled。2GB 服务器采集并发设为 1；摘要独立运行。
- 本地全国库快照迁移了 7179 篇 ready 政策（文档总表 7205 条），97 条 ready 摘要。原文及附件 8594 个对象逐一校验 SHA256 和长度，全部通过。
- 公网 HTTPS 验证了 `/health`、`/api/v2/regions`（32 个地区）、政策列表及真实摘要详情（506）。后台政策数随后增至 7191、摘要成功数增至 132，provider_error 为空，无异常重启；全量摘要仍在服务器继续生成。
- 小程序 develop/trial/release 均切换至 `https://wjwjwjw.top/api/v2`，7 组测试通过。微信小程序上传审核/发布未执行。
- 旧服务没有微信 AppID/AppSecret 配置；2026-11-18 用户补充了本机私密配置，并在腾讯云终端执行已上传的安装脚本。微信登录与账号收藏现已完成线上验证，详见下文。公开政策阅读与摘要不依赖登录。

## 目录与备份

- 新代码：`/home/ubuntu/weijianwei-releases/20261118-6d4c0d4`，后端基于提交 `6d4c0d4`；小程序环境文件同步了本次线上地址变更。
- 数据：`/home/ubuntu/weijianwei-data/national-service`，包含 `policy.db`、`objects`、`service.json` 和权限 600 的 `ai.env`。
- 旧代码保留在 `/home/ubuntu/nhc-project`，旧库 2553 篇、收藏数 0，未 reset 旧服务器的未提交改动。
- 备份：`/home/ubuntu/weijianwei-backups/20261118-before-v2`，含 SQLite 一致性备份、旧代码归档、原 systemd unit、Nginx 配置和临时端口日志。
- 安装日志：`/home/ubuntu/weijianwei-stage-20261118.log`，临时端口 8001 冒烟检查通过后才切换。
- 部署脚本：仓库 `deploy/production-cutover.py`，服务器 `/home/ubuntu/nhc-project/production-cutover.py`。

## 迁移包

本地 `.runtime/deploy-20261118/` 保留一致性快照和归档：

- `code.tar`：SHA256 `b670f183ed65d225b61695af8e968d413bc8a64fabd6723c1bb9b9411e414836`。
- `weijianwei-data.tar.gz`：SHA256 `d29d133469c4debe463e67334b1c3a40f93c67fa34e80e0029c22628f7075d82`，不含 AI 密钥。
- 两个归档在服务器重新校验通过，数据库 integrity_check 通过。
- AI 密钥直接从旧服务在服务器内继承，未上传或输出明文。

## 运维

```bash
systemctl status nhc-api weijianwei-worker weijianwei-summary
journalctl -u weijianwei-summary -u weijianwei-worker --since '10 minutes ago'
cd /home/ubuntu/weijianwei-releases/20261118-6d4c0d4/backend
venv/bin/python -m policy_v2.national_service summary-report --root /home/ubuntu/weijianwei-data/national-service
```

回滚命令（停止新版后台任务并恢复旧 API unit，保留新数据）：

```bash
python3 /home/ubuntu/nhc-project/production-cutover.py rollback
```

本机全国采集和摘要 launchd 保持停用，避免双端写入；独立三省试跑未改动。服务器数据此后为持续更新的主副本，本地快照不会自动同步服务器的新数据。若将任务迁回本机，应先停服务器写入并重新同步数据库与对象。

## 临时部署通道

腾讯云网页上传连接反复失败后，用户明确批准本次临时 SSH 登录。仅安装专用公钥，禁用转发和 PTY，设置两小时过期；服务器主机指纹通过腾讯云终端与 SSH 扫描核对一致。部署收尾已移除服务器临时公钥、授权脚本及本地临时私钥；重新连接返回 Permission denied，确认临时登录权限已撤销。三个生产服务在清理后仍为 active。

## 微信登录及账号收藏验收

2026-11-18 配置生效后，公开健康接口返回 ok，登录接口由 `503 wechat_login_not_configured` 变为拒绝无效凭证的 `401 wechat_code_invalid`。随后使用微信开发者工具的官方测试 SDK 获取真实 `wx.login()` 凭证，直接请求生产 HTTPS API，验证通过：

- AppID 与当前项目一致；真实凭证可建立账号会话。
- 收藏添加后可读回；重复添加同一政策仅保留一条。
- 再次微信登录后的新会话可读回同一账号收藏。
- 取消收藏后，另一会话也能读到取消结果。
- 测试结束恢复该政策原始收藏状态。

复验脚本 `scripts/test_production_wechat_favorites.cjs`，依赖已开启的本项目开发者工具测试端口 9420。它只输出通过状态，不打印 AppSecret、登录 code、openid 或会话 token。该验证覆盖开发者工具真实账号与线上服务器，不代表微信正式版已上传发布或手机 UI 已完成验收。

## 摘要范围调整（代码已完成，待服务器执行）

用户要求仅为最近三年的政策生成摘要。按北京时间滚动三个自然年，含首尾日期；2026-11-18 对应 2023-11-18 至 2026-11-18。本次线上查询共 7865 篇，其中 `published_since=2023-11-18` 为 3191 篇，最新发布日期为 2026-11-17；采集持续进行，数量会增长。

- 采集、检索和已生成摘要继续保留。缺少有效发布日期、超出日期范围的政策不调用 AI。
- 调度时取消范围外尚未完成的排队/失败任务，额度暂停期间也会清理；实际执行前再次检查日期。日期修正后可恢复符合条件的任务。
- 小程序增加范围外及日期未知的提示，不再对此类政策轮询摘要。
- 更新入口 `deploy/summary-window-update.py --revision <完整提交 SHA>`，校验源文件 SHA256，停止摘要 worker，备份原代码及一致性数据库，替换单个模块并清理任务，再重启 API 和摘要 worker。失败时恢复 API 代码并保持摘要 worker 停止。
- 线上尚未执行更新：先前临时 SSH 已撤销，浏览器自动操作遭安全审核阻止，需要用户在腾讯云终端执行准备好的命令。不得将代码提交当作已经上线。
- 限制范围不会解决已有的 DeepSeek `quota_exhausted`；恢复额度后才可继续生成符合条件的摘要。

### 摘要并发改为 10（待部署）

摘要 worker 使用 10 个线程并行请求 AI，配置项为 `POLICY_AI_CONCURRENCY=10`，修改并发数后重启摘要服务。每一路仍保留请求间隔，调度器统一补任务，停服务时等待在途请求结束。SQLite 领取任务在进程内串行处理，模型请求并行，避免线程争抢同一任务导致空等。共享额度/限流暂停只延长、不被其他并发失败缩短；发起请求前再次检查暂停状态。

更新后的 `deploy/summary-window-update.py` 一次部署最近三年限制与 10 路并发，校验并备份两个后端模块、数据库和权限为 600 的私密配置，写入并发配置，再重启服务。不需要先执行旧版命令。并发测试验证 10 个不同任务同时处理、停机不再领取任务且在途结果落库、并发额度/限流失败共享最长暂停。线上生效仍需执行新的固定版本更新命令。
