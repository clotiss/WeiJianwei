# 全国持久化数据与小程序接通

## 数据链路

新版小程序开发环境改为 `http://127.0.0.1:8892/api/v2`，API 与采集器共用 `.runtime/national-service/policy.db` 以及 `objects/`。不再依赖三省测试快照；该目录重启后保留，不随 API 退出删除。原三省连续观察库未修改。

先从 `evidence/national/trials-final.json` 对应的 1,135 篇真实原页建立初始库。导入前验证 58 个来源的配置哈希、每页 SHA-256、标题、日期和正文长度；导入解析后的完整正文和原始页面，不把验证报告摘要当作正文。46 份已有附件原件按哈希验证并复制；其余附件交给持久化任务队列。

首次导入产生 1,135 个版本，其中 4 篇由既有内容范围规则排除，初始可展示 1,131 篇。再次导入新增版本为 0；重复导入不会覆盖后来从官网获取的新版本。数据覆盖 28 省及国家的 58 个栏目，河北、山东、青海的 6 个未验证栏目不创建采集任务。

新服务使用新端口，也使本机阅读记录和账号缓存按 API 地址隔离，避免旧快照的数字文档 ID 被误用。体验版与线上正式版没有切换，真实微信登录仍需独立测试服务凭据和 HTTPS 合法域名。

## 历史回填与日常监控

- 已验证的 58 个栏目全部启用；每 6 小时开启新轮次，运行器每分钟检查调度。
- 首轮逐页扫描已登记栏目并收录正文，保存页码与任务依赖；每批 3 页后自动续接，进程重启从已提交位置继续。
- 列表发现优先级 5、正文 10、附件 20，避免初始附件积压阻止发现新文档；6 个工作线程，同域请求间隔 3 秒、数据库租约防止并发访问同域。
- 后续轮次复查前几页正文，深页未变化内容每 7 天复查；新增 URL 或列表标题／日期改变时立即抓取，不因碰到旧日期便提前终止列表扫描。
- 网络故障仍遵守同域冷却与 Retry-After；单篇内容解析异常保留任务和原页，不让整个网站进入冷却。下载和文字提取分别记录：原件已保存但提取超限／出错时，明确标记 `extraction_limited`／`extraction_failed`，不反复下载相同原件。
- 轮次只有在列表、正文与可下载附件任务完成后才标记成功。原件下载完成不等于已 OCR、音视频转写或分类人工验收。历史回填进度以运行状态为准，启动任务不算全量完成。

## 小程序行为

- 地区选项去掉“全国”，保留国家卫健委与 31 省，默认国家卫健委。
- 省份可单独查看，也可勾选同时包含国家级文件；搜索继承地区、类型、主题与日期。
- API 返回地区状态；页面区分“历史内容正在补录”“采集暂时受阻”“该地区来源尚未接通”“没有找到匹配的政策”和真正的零收录。
- 来源页显示每栏目已收录数量、已扫描页数、首轮回填状态、监控启停及最近完整采集时间。省份未接通时不会因同时包含国家文件而显示已接通。

## 运行与恢复

从仓库根目录初始化（需要保留的原页缓存，不会从测试报告生成虚构原文）：

```sh
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service import \
  --root .runtime/national-service --workspace "$PWD"
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service enable \
  --root .runtime/national-service
python3 scripts/manage_national_service.py install --root .runtime/national-service
```

安装器配置当前用户登录自启、异常退出重启，不需要 root。两个 launchd 标签为 `com.weijianwei.national-api`、`com.weijianwei.national-worker`；文件位于 `~/Library/LaunchAgents/`。这属于本机开发服务，Mac 休眠、关机或退出用户期间不能持续采集；恢复后沿用数据库游标和租约。要实现全天运行，仍需部署到常驻服务器。

```sh
# 直接运行：Linux 可用相同模块，交由 systemd 等进程管理器托管。
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service api \
  --root .runtime/national-service --port 8892
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service worker \
  --root .runtime/national-service --workers 6

# 状态与停止（停止同时移除这两个登录启动项，不删除数据）。
python3 scripts/manage_national_service.py status --root .runtime/national-service
PYTHONPATH=backend .venv/bin/python -m policy_v2.national_service report \
  --root .runtime/national-service
python3 scripts/manage_national_service.py stop --root .runtime/national-service
```

每分钟状态快照在 `.runtime/national-service/report.json`。日志位于 `/private/tmp/weijianwei-national-{api,worker}.log`。备份需使用 SQLite backup API 获取一致性数据库副本，并备份同目录的 `objects/`；不要只复制运行中的主 DB 文件而忽略 WAL。

## 验证与真实回填发现的问题

后端完整回归 **384 项通过**，前端 **6 组通过**，微信 WXML **14 个模板编译通过**。已验证真实缓存重复导入、旧缓存不能覆盖新版本、损坏原页拒绝导入、恢复相同数据库、仅启用已验证来源、日期筛选及关注权限、回填分页／重启／失败补偿。逐省微信模拟器验收确认 29 个地区有数据、58 个栏目启用、3 个阻塞地区提示正确、默认国家且无全国选项；原型筛选、分栏、关注／我的、阅读设置与浏览记录通过。

全国数据暴露了河南 PDF 字形映射中的孤立 UTF-16 代理字符，曾导致列表返回 500。新增提取阶段 Unicode 修复及旧 JSON 响应兼容，保留原始 PDF；实际河南接口和相关回归已恢复。另对超过 500 页 PDF、PDF 解析库异常与单篇正文异常补齐原件持久化及独立失败状态。

真实回填发现的北京视频页已补上 iframe 中的 MP4 原链接，标记待转写；修复后的原任务实际重试成功。贵州深页改用官网已存在的页码输入／确认按钮，并校验当前页；实测第 21 页正确返回末尾 4 条，减少逐页重放。只调整浏览器导航字段，列表与正文解析不变；旧游标经审核延续并写入审计，未重置历史进度。新增真实原页回归和 `evidence/national/gz-backfill-navigation-2026-11-17.json` 保留证据。

`evidence/national/national-service-2026-11-17.json` 保存本次测试、各地区发布日期范围、运行状态及原三省观察来源未被改变的检查结果。运行数量会继续增长，以实时 API 与 `report.json` 为准。

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
node miniprogram/tests/run.js
/Applications/wechatwebdevtools.app/Contents/MacOS/cli auto \
  --project "$PWD/miniprogram" --auto-port 9420
node scripts/test_miniprogram_national.cjs
node scripts/test_miniprogram_prototype.cjs
```

真实官网历史量较大，回填任务持续推进。测试通过不代表所有官网历史页均已成功收录；采集失败会保留任务、错误和重试状态，不以已有样本掩盖历史缺口。手机真机与腾讯云部署验收不计入本轮本机验证。
