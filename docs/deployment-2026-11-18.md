# 2026-11-18 生产部署

用户授权将 V2 部署到腾讯云并替换线上代码，明确无需兼容旧业务。

## 已上线

- 广州轻量实例 `lhins-gxfnimwx`，域名 `https://wjwjwjw.top`。
- 2026-11-18 10:58（北京时间）切换 `nhc-api`，新版独立入口 `policy_v2.app:app`，Nginx 继续转发至 `127.0.0.1:8000`。
- `nhc-api`、`weijianwei-worker`、`weijianwei-summary` 均 active、enabled。2GB 服务器采集并发设为 1；摘要独立运行。
- 本地全国库快照迁移了 7179 篇 ready 政策（文档总表 7205 条），97 条 ready 摘要。原文及附件 8594 个对象逐一校验 SHA256 和长度，全部通过。
- 公网 HTTPS 验证了 `/health`、`/api/v2/regions`（32 个地区）、政策列表及真实摘要详情（506）。后台摘要成功数随后增至 103，provider_error 为空，无异常重启；全量摘要仍在服务器继续生成。
- 小程序 develop/trial/release 均切换至 `https://wjwjwjw.top/api/v2`，7 组测试通过。微信小程序上传审核/发布未执行。
- 旧服务没有微信 AppID/AppSecret 配置。新版微信登录、账号收藏等功能仍需配置 `POLICY_WECHAT_APP_ID` 和 `POLICY_WECHAT_SECRET`；公开政策阅读与摘要不依赖登录。

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

腾讯云网页上传连接反复失败后，用户明确批准本次临时 SSH 登录。仅安装专用公钥，禁用转发和 PTY，设置两小时过期；服务器主机指纹通过腾讯云终端与 SSH 扫描核对一致。部署收尾须移除该临时公钥及本地私钥，并验证已不能重新登录。
