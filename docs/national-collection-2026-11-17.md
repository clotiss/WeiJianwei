# 全国采集框架与接入验收记录

日期：2026-11-17。范围：国家卫健委，以及大陆 31 个省、自治区、直辖市的省级卫健委官网政策/解读入口。市县、医院招聘、其他政府部门不在本轮接入范围；原有招聘开关继续保留。

## 完成结果

- 31 个省级官网已登记，目录包含 62 个省级栏目槽位及 2 个国家栏目。
- 28 省及国家的 58 个栏目已配置并通过本轮抽样：1,135 篇原文。通常每栏 20 篇；吉林解读遍历全栏后仅 5 篇，西藏规范性文件栏符合范围的站内原文为 10 篇，均已检查。
- 河北、山东、青海的 6 个栏目尚未达到自动采集接入条件。黑龙江在后续排查中通过官网公开 HTTP 接口接通，证书问题本身仍未修复。
- 290 份真实列表/详情样本已压缩入库，可在不访问官网的情况下回归正文模板、日期、标题、附件和翻页。
- 46 个代表性附件下载并持久化成功：16 个已提取文字，26 个图片/扫描件标记 `needs_ocr`，4 个旧 Office/WPS 文件保留原件并标记 `unsupported`。其中部分图片是正文中的嵌入资源，统计不等同于 26 篇完整图解已完成 OCR。
- 本轮只在本地做开发与采集验证；新来源默认关闭，保留已存在来源的启停状态，未部署或启用线上全国采集。

“抽样通过”表示所列样本可解析，不等同于全历史完整、政策分类经人工验收或多日生产稳定。地区字段表示采集站点归属；站点转载国家政策时不据此推定发文机关。`authority` 当前采用官网 ContentSource 来源署名，并不保证等同于实际发文机关，需要人工校验；缺失时保留空值。

## 逐省结果

批次按每组最多 5 省划分；国家栏目独立为批次 0。页数为实际检查列表页数，不是已回填全站的页数。

| 批次 | 官网 | 政策文件 | 政策解读 | 范围或限制 |
| --- | --- | --- | --- | --- |
| 1 | [北京](https://wjw.beijing.gov.cn) | [通过 20/20](https://wjw.beijing.gov.cn/zwgk_20040/zcwj2024/zcwjss/)；3 页 | [通过 20/20](https://wjw.beijing.gov.cn/zwgk_20040/zcjd2024/)；3 页 |  |
| 1 | [天津](https://wsjk.tj.gov.cn) | [通过 20/20](https://wsjk.tj.gov.cn/ZWGK3158/ZCFG6243_1/)；7 页 | [通过 20/20](https://wsjk.tj.gov.cn/ZWGK3158/ZCJD2018/zcjd0971/)；4 页 |  |
| 1 | [河北](https://wsjkw.hebei.gov.cn/) | 阻塞：browser_challenge | 阻塞：browser_challenge | 普通 Chrome 可打开；独立 Firefox/Chrome 会话只收到脚本页面，无有效列表。 |
| 1 | [山西](https://wjw.shanxi.gov.cn) | [通过 20/20](https://wjw.shanxi.gov.cn/zfxxgk/fdzdgknr/flfg/gfxwj/)；2 页 | [通过 20/20](https://wjw.shanxi.gov.cn/tzgg/zcjd/index.shtml)；3 页 |  |
| 1 | [内蒙古](https://wjw.nmg.gov.cn) | [通过 20/20](https://wjw.nmg.gov.cn/zfxxgk/fdzzgknr/gfxwj/)；3 页 | [通过 20/20](https://wjw.nmg.gov.cn/zfxxgk/fdzzgknr/zcjd/)；3 页 |  |
| 2 | [辽宁](https://wsjk.ln.gov.cn) | [通过 20/20](https://wsjk.ln.gov.cn/wsjk/zfxxgk/zc/xzgfxwj91/index.shtml)；2 页 | [通过 20/20](https://wsjk.ln.gov.cn/wsjk/index/syxwxx/zcjd/index.shtml)；3 页 |  |
| 2 | [吉林](https://wsjkw.jl.gov.cn) | [通过 20/20](https://wsjkw.jl.gov.cn/zfxxgk/zfwj/gfxwj/)；7 页 | [通过 5/5](https://wsjkw.jl.gov.cn/zfxxgk/zfwj/gfxwj/)；7 页 | 混合栏目按标题分流；解读遍历 7 页后只有 5 篇符合范围。 |
| 2 | [黑龙江](https://wsjkw.hlj.gov.cn) | [通过 20/20](http://wsjkw.hlj.gov.cn/wsjkw/c109073/zfxxgk.shtml?tab=gfxwj)；8 页 | [通过 20/20](http://wsjkw.hlj.gov.cn/wsjkw/c109075/zfxxgk.shtml?tab=zcjd)；9 页 | 官网公开 HTTP 接口；无认证传输保障。文件列表 160 条，解读 177 条中 174 条站内、3 条外链过滤。仅正文抽样，未全量回填。 |
| 2 | [上海](https://wsjkw.sh.gov.cn) | [通过 20/20](https://wsjkw.sh.gov.cn/swsjswgfxwj/index.html)；3 页 | [通过 20/20](https://wsjkw.sh.gov.cn/zcjd/)；3 页 |  |
| 2 | [江苏](https://wjw.jiangsu.gov.cn) | [通过 20/20](https://wjw.jiangsu.gov.cn/col/col81326/index.html)；2 页 | [通过 20/20](https://wjw.jiangsu.gov.cn/col/col7292/index.html)；2 页 |  |
| 3 | [浙江](https://wsjkw.zj.gov.cn/) | [通过 20/20](https://wsjkw.zj.gov.cn/col/col1229055217/index.html)；3 页 | [通过 20/20](https://wsjkw.zj.gov.cn/col/col1229055223/index.html)；3 页 |  |
| 3 | [安徽](https://wjw.ah.gov.cn) | [通过 20/20](https://wjw.ah.gov.cn/public/column/7001?type=6&action=xinzheng)；3 页 | [通过 20/20](https://wjw.ah.gov.cn/public/column/7001?type=4&catId=43797231&action=list&nav=3)；3 页 |  |
| 3 | [福建](https://wjw.fujian.gov.cn/) | [通过 20/20](https://wjw.fujian.gov.cn/xxgk/fgwj/zxwj/)；8 页 | [通过 20/20](https://wjw.fujian.gov.cn/xxgk/fgwj/zcjd/bmzcjd/)；8 页 | 验证第 8 页，跨过预载 70 条；官网显示文件 2605 条、解读 222 条，未全量回填。 |
| 3 | [江西](https://hc.jiangxi.gov.cn) | [通过 20/20](https://hc.jiangxi.gov.cn/jxswsjkwyh/gfxwj116/pc/list.html)；3 页 | [通过 20/20](https://hc.jiangxi.gov.cn/jxswsjkwyh/jdcl117/pc/list.html)；3 页 |  |
| 3 | [山东](https://wsjkw.shandong.gov.cn/) | 阻塞：connection_timeout | 阻塞：connection_timeout | 本机 HTTPS 和普通 Chrome 超时，腾讯云服务器连接失败；尚不能区分官网故障与网络出口问题。 |
| 4 | [河南](https://wsjkw.henan.gov.cn) | [通过 20/20](https://wsjkw.henan.gov.cn/zfxxgk/gfxwj/)；3 页 | [通过 20/20](https://wsjkw.henan.gov.cn/zfxxgk/xxgkml/zcfg/zcjd/)；3 页 |  |
| 4 | [湖北](https://wjw.hubei.gov.cn) | [通过 20/20](https://wjw.hubei.gov.cn/zfxxgk/zc/gfwj/)；2 页 | [通过 20/20](https://wjw.hubei.gov.cn/zfxxgk/zc/zcjd_1/)；3 页 |  |
| 4 | [湖南](https://wjw.hunan.gov.cn/) | [通过 20/20](https://wjw.hunan.gov.cn/wjw/xxgk/zcfg/gfxwj/index.html)；3 页 | [通过 20/20](https://wjw.hunan.gov.cn/wjw/xxgk/zcfg/zcjd/index.html)；3 页 | 前轮 TLS EOF；本轮通过，连续运行稳定性待观察。 |
| 4 | [广东](https://wsjkw.gd.gov.cn) | [通过 20/20](https://wsjkw.gd.gov.cn/hdjl/hdjl_zcwj/index.html)；2 页 | [通过 20/20](https://wsjkw.gd.gov.cn/hdjl_zcjd/index.html)；3 页 |  |
| 4 | [广西](https://wsjkw.gxzf.gov.cn/) | [通过 20/20](https://wsjkw.gxzf.gov.cn/xxgk_49493/xzghxwj/)；3 页 | [通过 20/20](https://wsjkw.gxzf.gov.cn/xxgk_49493/fdzdgk/gkwj/zcjd/)；3 页 |  |
| 5 | [海南](https://wst.hainan.gov.cn/) | [通过 20/20](https://wst.hainan.gov.cn/swjw/xxgk/gfxwj/index.html)；3 页 | [通过 20/20](https://wst.hainan.gov.cn/swjw/jdhy/zcjd/zxjd/)；3 页 |  |
| 5 | [重庆](https://wsjkw.cq.gov.cn) | [通过 20/20](https://wsjkw.cq.gov.cn/zwgk_242/zfxxgkml/zcwj/xzgfxwj2/)；3 页 | [通过 20/20](https://wsjkw.cq.gov.cn/zwgk_242/zcjd/wzjd/)；3 页 | 当前解读入口为文字解读栏目；其他子栏目未宣称覆盖。 |
| 5 | [四川](https://wsjkw.sc.gov.cn) | [通过 20/20](https://wsjkw.sc.gov.cn/scwsjkw/xzgfxwj/gfxwj_new.shtml)；5 页 | [通过 20/20](https://wsjkw.sc.gov.cn/scwsjkw/zcjdp/tygl.shtml)；7 页 |  |
| 5 | [贵州](https://wjw.guizhou.gov.cn/) | [通过 20/20](https://wjw.guizhou.gov.cn/zwgk/gzhgfxwjsjk/gfxwjsjk/index.html)；7 页 | [通过 20/20](https://wjw.guizhou.gov.cn/zwgk/jcxxgk/zcjd/)；7 页 |  |
| 5 | [云南](https://ynswsjkw.yn.gov.cn/) | [通过 20/20](https://ynswsjkw.yn.gov.cn/zwgk/zcwj/xzgfxwj/)；2 页 | [通过 20/20](https://ynswsjkw.yn.gov.cn/zwgk/zcwj/zcjd/)；6 页 |  |
| 6 | [西藏](https://wjw.xizang.gov.cn/) | [通过 10/10](https://wjw.xizang.gov.cn/zwgk/xzgfxwj/)；1 页 | [通过 20/20](https://wjw.xizang.gov.cn/zwgk/zcjd/)；3 页 | 规范性栏目 12 条中 10 条站内原文纳入，2 条外链记入过滤审计。 |
| 6 | [陕西](https://sxwjw.shaanxi.gov.cn/) | [通过 20/20](https://sxwjw.shaanxi.gov.cn/zfxxgk/fdzdgknr/zcwj/xzgfxwj/)；3 页 | [通过 20/20](https://sxwjw.shaanxi.gov.cn/zfxxgk/zcjd/)；3 页 |  |
| 6 | [甘肃](https://wsjk.gansu.gov.cn) | [通过 20/20](https://wsjk.gansu.gov.cn/wsjk/c117380/xxgk_list2.shtml)；3 页 | [通过 20/20](https://wsjk.gansu.gov.cn/wsjk/c113462/xxgk_list2.shtml)；3 页 |  |
| 6 | [青海](https://wsjkw.qinghai.gov.cn) | 阻塞：http_412 | 阻塞：http_412 | 普通 Chrome 可打开；采集返回 412，独立浏览器会话最终 400 空页。 |
| 6 | [宁夏](https://wsjkw.nx.gov.cn) | [通过 20/20](https://wsjkw.nx.gov.cn/zfxxgk_279/fdzdgknr/gfxwj/)；2 页 | [通过 20/20](https://wsjkw.nx.gov.cn/zfxxgk_279/zcfgjd/)；3 页 |  |
| 7 | [新疆](https://wjw.xinjiang.gov.cn/) | [通过 20/20](https://wjw.xinjiang.gov.cn/hfpc/zcwj4/zfxxgk_gknrz.shtml)；3 页 | [通过 20/20](https://wjw.xinjiang.gov.cn/hfpc/zcjd/zfxxgk_gknrz.shtml)；3 页 |  |

国家卫健委：规范性文件与解读各 20/20，列表各检查 3 页。

## 四省问题的追加排查

最初将河北、黑龙江、山东、青海登记为阻塞，表示当时没有通过可重复的采集验证，并不表示无法解决。此次对照了本机请求、正常用户 Chrome、独立 Firefox/Chrome 会话和腾讯云服务器，只改动本地代码与验证资料。

黑龙江的 HTTPS 证书过期，但同一官网的公开目录接口、正文及附件可经 HTTP 读取。新增 `government-json` 适配器，按实际栏目 ID、记录总数和页码校验；不足一页却声称还有记录、错页、错栏目或缺失日期均报错，防止静默漏抓。8 页文件列表和 9 页解读列表已读到末页，正文各抽查 20 篇。两份代表性附件已保存；PDF/DOC 文件小图标已从正文图片中排除，国家栏目的同类图标也不再计入最终附件统计。限定 `public_http_hosts` 只对黑龙江该来源的官网生效，不自动降级其他 HTTPS 地址，不放行外域、非公开 IP、凭据或非常规端口；HTTPS 仍校验证书。HTTP 缺少认证传输保障，来源保持关闭，官网证书恢复后应重新验证并切回 HTTPS。

河北、青海在用户正常 Chrome 中能显示首页及政策栏目链接，但独立 Firefox、Chrome、可见窗口、新建持久会话均不能获得有效正文。移除 Chrome 自动化标记的实验曾被自动审批拦截，经用户明确授权仅测试这两个官网后执行，结果仍无改善；该实验参数未加入生产采集代码。直达已确认的栏目地址也分别得到脚本页及 HTTP 412。由此只能确定会话行为有差异，尚不能证明具体是哪个识别规则；“换 Firefox”或“去掉一个标记”目前都不能解决。已记录栏目入口，后续需要验证站点支持的自动访问方式或取得公开接口/采集白名单，不能将人工可浏览等同于自动采集通过。

山东在本机客户端和普通 Chrome 中超时，腾讯云终端复测连接失败；没有找到可验证的完整备用官方栏目。这一阶段不能断言是官网整体停服，也不能靠修改正文选择器解决。后续需定位官网或网络出口连通性，或验证省政府统一政策库的卫健委筛选入口及覆盖范围；其他部门转载的零散文件不能代替整站覆盖。

本轮对比证据见 `evidence/national/blocked-followup-2026-11-17.json`。未解决的三省仍保留 `blocked`，所有新来源继续默认关闭。

## 实现方式

`registry/provinces.json` 管理地区、官网、来源证据和批次；`registry/sources.json` 管理栏目入口、模板参数、分页、传输方式、允许访问的域名及验证状态。阻塞项 `config=null`，不会创建可运行采集源。`/api/v2/source-inventory` 展示完整登记与验证状态；`/api/v2/coverage` 仍展示实际运行源状态，登记不代表已上线。

同一套 `adapters.read_list → parse_detail → pipeline` 处理 HTML/TRS、JCMS XML、公开 JSON 列表、异步浏览器列表、静态页码和动态翻页。网站差异保留在来源配置，新增省份不需要复制整个爬虫。特殊新站型可增加适配器，仍复用任务、存储和审计流程。

独立工作线程各自持有 HTTP/Firefox 会话。数据库域名租约将同一来源允许的官网、重定向及资源域名一起预留，避免多个工作线程同时请求同域；这是一种保守策略，共用 CDN 的来源可能降低并行度。不同域可并行。请求结束后保留间隔；失败与 Retry-After 冷却写入数据库。任务和域名租约均续期，任务提交时重新检查所有权，崩溃后可回收，旧工作线程不能提交新拥有者的结果。

调度每分钟检查已启用来源，按来源间隔和时间桶幂等入队。默认每轮最多 3 个列表页，配置上限 100 页；动态“下一页”方式到深页时需逐页重放，不适合直接大规模历史回填。历史回填应单独规划检查点及批量窗口，本轮未启动全国历史回填。

原始页面快照和附件采用 SHA-256 内容寻址存储，文档版本保留快照引用及附件提取状态。正文内图片保留并标记待 OCR；视频/音频原链接保留为 `needs_transcription`，不自动下载或假装已转写。未登记的附件外域保留 `external_reference`，不会无限失败重试；已确认的河南文件域、浙江省政府 CDN 已登记。内联图片随原始 HTML 保留，标记 `embedded`。

附件下载对 HTML 错误页和真正二进制文件分别校验。江苏下载接口虽返回 `text/html`，实际为 DOCX，通过文件头确认后解析；浙江下载经过已验证的官方 CDN；江西、甘肃及江苏使用 Firefox 会话读取有大小上限的二进制流。TLS 校验保持开启。

列表审计保存原始条数、合格条数、外域/内容类型/重复过滤数和翻页信息。江苏微信等外链仍排除并计数。对征求意见、招聘等已有排除规则保留；“部门文件”宽栏目中的通知、奖项、考试等文种，仍需后续内容规则及人工抽检，当前结果不声称分类准确率已达标。

## 重跑与运行

从仓库根目录执行，先安装 `backend/requirements-v2.txt` 及对应 Playwright Firefox。以下验证脚本只读取官网，不启用来源：

```bash
PYTHONPATH=backend .venv/bin/python -m policy_v2.cli inventory
PYTHONPATH=backend .venv/bin/python scripts/validate_national.py --batch 1 --pages 3 --output .runtime/batch-1.json
PYTHONPATH=backend .venv/bin/python scripts/validate_national.py --region JL --pages 7 --output .runtime/jilin.json
PYTHONPATH=backend .venv/bin/python scripts/validate_national.py --region FJ --pages 8 --output .runtime/fujian.json
PYTHONPATH=backend .venv/bin/python scripts/validate_national.py --region HLJ --pages 9 --output .runtime/heilongjiang.json
```

默认复用已保留页面；要衡量当前连通性，添加 `--refresh`。缓存解析通过不能代替实时连通性检查。每个脚本内部最多 4 个域并行、同域顺序访问；不要对同一域同时启动多个独立验证脚本。

附件抽样：

```bash
PYTHONPATH=backend .venv/bin/python scripts/validate_national_attachments.py --output .runtime/attachments.json
```

后台工作进程仅消费已启用来源。正式运行前配置数据库、对象存储、管理员认证和运行监控；在管理接口逐源审核启用，默认不自动开启全国来源：

```bash
PYTHONPATH=backend .venv/bin/python -m policy_v2.cli worker --workers 4
```

测试结果：追加修复后后端 351 项通过；此前小程序 API 适配器 6 项和首页容错测试通过，本次未改动前端。现有依赖产生弃用警告，无失败测试。

测试命令：

```bash
PYTHONPATH=backend .venv/bin/pytest -q backend/tests
node miniprogram/tests/api-v2.test.js
node miniprogram/tests/index-resilience.test.js
```

## 证据与仍需完成的验收

- `evidence/national/trials-final.json`：最终样本、来源配置哈希、日期、解析结果、过滤审计与翻页。
- `evidence/national/attachments-final.json`：46 个附件的 URL、哈希、字节数、存储键及提取状态。
- `backend/tests/fixtures/national/manifest.json`：290 份压缩原始页面和离线回归期望。
- `evidence/national/hlj-recovery-pagination.json`：黑龙江完整列表翻页和 40 篇正文抽样；`hlj-recovery-attachments-final.json` 为去除文件图标后的附件验证。
- 其他 `trials-*.json`、`attachments-*.json` 和 `inspections.json`：保留接入过程中的失败与修复证据，不以最终成功记录掩盖历史故障。
- 验证期间的完整原文和附件留存在本地 `.runtime/national/`，该目录不提交 Git。Git 中保存代表性原页；生产采集使用配置的本地/COS 对象存储，而非依赖这些测试缓存。

后续上线验收包括：从部署服务器复测所有来源、至少连续 3–7 天观察调度与增量更新、关闭再启动后的补偿测试，以及定期人工检查标题/日期/文种/发布机关和附件完整性。湖南已有间歇性 TLS EOF，需重点观察。河北、山东和青海继续保持未接入状态；黑龙江为显式公开 HTTP 方案，需要单独审核传输限制。不得通过关闭证书校验或使用非官网镜像将来源标记通过。
