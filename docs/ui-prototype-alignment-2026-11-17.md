# 小程序评审原型落地记录

## 基准与范围

设计基准是工作区 `outputs/weijianwei-review-v1/index.html#ui`（2026-11-16 原型），并遵循同目录 `development-plan.html` 的后续范围收敛：底部“政策／关注／我的”三个入口；隐藏招聘入口；不单列意见征集；保留后端现有八类业务主题。

此前 V2 接口接入保留了旧版蓝色布局，本次已替换。沿用微信原生顶部导航和底部 tabBar，以适配返回行为、安全区与平台交互；内容区、卡片、配色、图标、抽屉和详情层次按原型实现。

## 已落地

| 界面 | 实际行为 |
| --- | --- |
| 政策首页 | 白色导航、浅色背景、紧凑搜索栏、政策正文／官方解读、主题快捷筛选、青色关注提示卡、真实政策卡片 |
| 地区抽屉 | 全国、国家及 31 省；按官网来源地区过滤；可排除国家级文件；确认后应用，取消不改条件 |
| 筛选抽屉 | 类型、八类业务主题、近 7／30／90 天；支持重置；筛选范围继承到搜索 |
| 政策详情 | 标题及来源信息、要点／正文／附件、可选择复制的正文、大字阅读、底部收藏与官方来源链接 |
| 关注 | 添加或删除地区／主题规则；选择规则查看相关政策；服务端保存，不自动发送微信推送 |
| 我的 | 账号收藏与关注计数、最近 50 条本机浏览记录、大字正文开关、数据覆盖入口 |

原型中的示例数量、假摘要、虚构抓取时间没有写入界面。接口缺失摘要时明确显示“本篇暂未生成要点”；未标注发布机构时提示核对原文。无附件、失败、无数据、账号功能不可用均有对应状态。官网和附件链接通过复制后在浏览器打开，未声称支持微信内跨域预览。

## 对应接口与资源

- `GET /api/v2/policies` 新增经日期类型校验的 `published_since`，包含起始日期；关键词新增匹配发布机构。
- `DELETE /api/v2/me/follows/{id}` 仅允许当前登录账号删除自己的规则。
- 收藏列表并发读取合并，保留环境与账号会话隔离；失败不显示写入成功。
- 原型线性 SVG 图标转为透明 PNG，用于小程序原生 tabBar 和内容区。源数据位于 `miniprogram/assets/icons/sources.json`，仅构建使用，运行时不 require JSON。重建：

```sh
npm install --prefix .runtime/icon-render --ignore-scripts @resvg/resvg-js
node scripts/build_ui_icons.cjs
```

## 验证

- `node miniprogram/tests/run.js`：6 组通过，包含真实 FastAPI 契约、搜索与筛选传递、收藏／关注读写、失败恢复、微信模块加载。
- 隔离临时 SQLite 数据库中执行 `backend/tests/test_policy_v2_api.py`：8 项通过，覆盖日期边界、非法日期、机构搜索及跨账号取消关注保护。
- 微信 WXML 编译器检查所有模板通过。
- 微信开发者工具官方自动化 SDK：首页、筛选、搜索、详情、正文和覆盖页通过；新增原型专项验证地区／日期抽屉、详情分栏、关注／我的导航、浏览记录和大字阅读。
- 人工检查 SDK 截图，修正了微信原生按钮默认宽度／边距导致的卡片排版问题；打开抽屉时隐藏底部原生 tabBar，关闭时恢复。

复验（开发者工具服务端口和本机预览后端需运行）：

```sh
/Applications/wechatwebdevtools.app/Contents/MacOS/cli auto \
  --project "$PWD/miniprogram" --auto-port 9420
node scripts/test_miniprogram_simulator.cjs
node scripts/test_miniprogram_prototype.cjs
```

截图保存在本机 `.runtime/prototype-{home,region,filter,detail,follow,mine}-actual.png`。自动化通过页面／组件交互方法及渲染结果验证；未将原生 picker 手势、微信扫码登录或 iOS／Android 手机验收计为通过。

## 本机预览与后续验收

预览读取三省监控库的只读备份，当前快照 294 条。已重新加载后端以支持日期筛选；全国采集逻辑和独立三天监控任务未改动。

当前预览由本机临时服务 `com.weijianwei.miniprogram-preview` 运行，配置位于 `.runtime/miniprogram-preview/preview.plist`，日志在 `/private/tmp/weijianwei-miniprogram-preview.log`。未安装登录自启项。停止后可按接入记录重新启动前台预览：

```sh
launchctl bootout "gui/$(id -u)/com.weijianwei.miniprogram-preview"
PYTHONPATH=backend .venv/bin/python scripts/serve_miniprogram_preview.py \
  --snapshot-from .runtime/monitor-trial-20261117/trial.db
```

本机快照服务有意关闭真实微信登录，所以云收藏／关注同步在此环境提示“账号同步暂未开放”；契约测试使用隔离库验证读写与权限。上线前仍需独立 HTTPS 测试服务、真实微信登录和手机验收。体验版地址尚未配置，正式版仍指向 V1，本次未上传或发布小程序。
