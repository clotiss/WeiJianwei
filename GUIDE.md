# NHC 政策文件小程序 — 完整开发指南

本文档面向没有小程序开发经验的人，从零到上线的全流程。

------

## 一、项目简介

### 做什么

一个微信小程序，自动抓取国家卫健委官网的政策文件，用 AI 生成摘要和分类，用户在小程序里浏览、搜索、收藏。

### 技术栈

| 层级 | 技术 | 作用 |
|------|------|------|
| 前端 | 微信小程序原生框架 | 用户界面，在微信内运行 |
| 后端 | Python FastAPI | 提供 API 接口 |
| 数据库 | SQLite | 存储文件数据 |
| 爬虫 | Playwright + Firefox | 绕过反爬抓取卫健委网站 |
| AI | DeepSeek V4 Pro API | 自动分类 + 生成摘要 |
| 部署 | 腾讯云服务器 + Nginx + HTTPS | 让外网能访问后端 |

### 为什么前后端分离

- 后端：在服务器上定时抓取数据、存库、提供 API。必须有公网 HTTPS 才能让小程序调用。
- 前端：上传到微信服务器，用户打开小程序时加载。

用户打开小程序 → 前端从微信服务器加载 → 调用后端 API → 拿到数据显示。

------

## 二、环境准备

### 2.1 注册账号

你需要注册以下账号：

| 平台 | 地址 | 用途 |
|------|------|------|
| 微信小程序 | mp.weixin.qq.com | 管理小程序、上传审核 |
| DeepSeek | platform.deepseek.com | AI 摘要的 API Key |
| 腾讯云 | cloud.tencent.com | 云服务器 + 域名 + 备案 |

### 2.2 本地开发工具

Mac 上安装：

- **微信开发者工具**：developers.weixin.qq.com 下载
- **Python 3.10+**：`brew install python@3.12`
- **Git**：代码版本管理

### 2.3 创建小程序项目

1. 微信公众平台 → 注册小程序（个人主体即可）
2. 完成基本信息：名称、头像、服务类目
3. 记下 AppID（如 `wx2672b8c409de2b18`）

------

## 三、项目结构

```
XcxProject/
├── backend/                  # 后端代码
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 配置文件
│   ├── database.py           # 数据库连接
│   ├── models.py             # 数据表定义
│   ├── schemas.py            # API 数据格式
│   ├── requirements.txt      # Python 依赖
│   ├── api/
│   │   ├── documents.py      # 文件列表、搜索、分类接口
│   │   └── favorites.py      # 收藏接口
│   └── services/
│       ├── scraper.py        # NHC 网站爬虫
│       ├── summary.py        # AI 分类 + 摘要
│       └── scheduler.py      # 定时抓取调度
├── miniprogram/              # 前端代码
│   ├── app.js                # 入口，全局配置
│   ├── app.json              # 页面路由、窗口样式
│   ├── app.wxss              # 全局样式
│   ├── project.config.json   # 微信工具配置
│   ├── sitemap.json          # 站点地图
│   ├── pages/
│   │   ├── index/            # 首页
│   │   ├── category/         # 分类列表
│   │   ├── detail/           # 文件详情
│   │   ├── search/           # 搜索页
│   │   └── favorites/        # 收藏页
│   └── utils/
│       ├── api.js            # API 请求封装
│       ├── storage.js        # 本地存储
│       └── swipe-back.js     # 右滑返回手势
├── TODO.md                   # 待办事项
└── GUIDE.md                  # 本文档
```

------

## 四、后端开发

### 4.1 创建虚拟环境

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install firefox --with-deps
```

### 4.2 配置文件

`config.py` 中修改：

```python
DEEPSEEK_API_KEY = "你的 API Key"  # 从 platform.deepseek.com 获取
DEEPSEEK_MODEL = "deepseek-v4-pro"  # 或 deepseek-v4-flash
SCRAPER_INTERVAL_HOURS = 6  # 爬取间隔
```

### 4.3 启动后端

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://localhost:8000/docs` 可以看到 API 文档。

### 4.4 触发爬取

```bash
python -c "import asyncio; from services.scraper import run_scrape_pipeline; asyncio.run(run_scrape_pipeline())"
```

首次爬取会抓 3 页（约 60 条），之后增量只抓 1 页，按 URL 去重。

### 4.5 爬虫原理

NHC 网站有 WZWS WAF 反爬保护。用 Playwright + Firefox 无头浏览器模拟真实访问：

1. 打开列表页 → 等待 JS 渲染 → 提取标题、日期、链接
2. 进入详情页 → 等待 2 秒 JS 渲染 → 提取正文和附件
3. URL 去重入库

两类来源：
- 规范性文件：`/wjw/gfxwjj/list.shtml`
- 政策解读：`/wjw/zcjd/list.shtml`

### 4.6 AI 分类

一次 DeepSeek API 调用同时完成分类和摘要，分类体系：

1. 综合与健康促进
2. 医疗机构与执业人员管理
3. 医疗服务与质量安全
4. 疾病预防控制与公共卫生
5. 妇幼健康与人口发展
6. 中医药与民族医药
7. 卫生监督与行政执法
8. 卫生信息化与标准

------

## 五、前端开发

### 5.1 导入项目

1. 打开微信开发者工具
2. 新建项目 → 目录选择 `miniprogram/`
3. AppID 填你的小程序 AppID
4. 创建后即可在模拟器中预览

### 5.2 页面结构

每个页面由 4 个文件组成：

| 文件 | 作用 |
|------|------|
| `.wxml` | 页面结构（类似 HTML） |
| `.wxss` | 页面样式（类似 CSS） |
| `.js` | 页面逻辑 |
| `.json` | 页面配置 |

### 5.3 连接后端

`app.js` 中的 `API_BASE` 控制请求地址：

```javascript
// 本地开发
API_BASE: 'http://localhost:8000/api/v1'

// 服务器部署（用域名）
API_BASE: 'https://你的域名/api/v1'
```

本地开发时，微信开发者工具需勾选：详情 → 本地设置 → 不校验合法域名。

### 5.4 主题色

全局主题色：`#1a6fb5`（政务蓝），定义在各页面 wxss 中。修改它即可全局换肤。

------

## 六、服务器部署

### 6.1 购买服务器

腾讯云 → 云服务器 CVM → Ubuntu 22.04（比 Windows 简单太多）。

最低配置：1 核 2G 内存即可。

### 6.2 登录服务器

在腾讯云安全组放行 TCP 22 端口。

```bash
ssh ubuntu@你的服务器IP
```

### 6.3 上传代码

```bash
scp -r backend ubuntu@你的服务器IP:/home/ubuntu/nhc-project/
```

### 6.4 安装依赖

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nginx firefox-esr
cd /home/ubuntu/nhc-project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install firefox --with-deps
```

### 6.5 配置开机自启

创建 `/etc/systemd/system/nhc-api.service`：

```ini
[Unit]
Description=NHC Policy API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/nhc-project
Environment=DEEPSEEK_API_KEY=你的APIKey
ExecStart=/home/ubuntu/nhc-project/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl start nhc-api
sudo systemctl enable nhc-api
```

### 6.6 购买域名 + DNS 解析

腾讯云 → 域名注册 → 购买域名（最便宜的即可，几元/年）

DNS 解析：添加 A 记录，将域名指向服务器 IP。

### 6.7 申请 SSL 证书 + 配置 Nginx

腾讯云 → SSL 证书 → 申请免费 DV 证书 → 下载 Nginx 格式

上传证书到服务器：

```bash
scp your-cert.pem ubuntu@IP:/home/ubuntu/
scp your-cert.key ubuntu@IP:/home/ubuntu/
```

服务器上配置 nginx：

```nginx
server {
    listen 443 ssl;
    server_name 你的域名 www.你的域名;

    ssl_certificate /etc/ssl/nhc/cert.pem;
    ssl_certificate_key /etc/ssl/nhc/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
sudo nginx -t && sudo systemctl restart nginx
```

### 6.8 ICP 备案

腾讯云 → ICP 备案 → 提交个人备案

备案通过前域名会被运营商拦截（HTTPS TLS 握手阶段 RST），可以暂时用 IP 地址在开发者工具中测试，等备案通过后切换回域名。

------

## 七、发布上线

### 7.1 微信公众平台配置

- 开发 → 开发管理 → 服务器域名 → request 合法域名 → 添加 `https://你的域名`
- 功能 → 订阅消息 → 申请模板（用于推送新文件提醒）

### 7.2 上传小程序

1. 微信开发者工具 → 上传 → 版本号 0.1.0
2. 微信公众平台 → 管理 → 版本管理 → 开发版本 → 选为体验版
3. 用体验版二维码测试
4. 测试通过 → 提交审核
5. 审核通过（通常 1-3 天）→ 发布上线

------

## 八、常见问题

### Q1: 微信开发者工具网络请求失败

检查：详情 → 本地设置 → 勾选"不校验合法域名、TLS 版本、HTTPS 证书"

### Q2: curl 能通但微信开发工具不通

通常是 SSL 证书链不完整或 TLS 版本不兼容 → 检查 nginx 配置，确保 `ssl_protocols TLSv1.2 TLSv1.3`

### Q3: 国内服务器域名无法访问

ICP 备案未通过，运营商拦截。备案通过前只能用 IP 在模拟器测试。

### Q4: 真机扫码没有数据

手机需开启调试模式：小程序内右上角 ... → 开发调试 → 开启。

### Q5: DeepSeek API 返回空

检查 API Key 是否正确设置，确认模型名称是 `deepseek-v4-pro` 或 `deepseek-v4-flash`。

### Q6: 爬虫返回空列表

NHC 网站升级了 WAF 反爬 → 检查 scraper.py 中的 User-Agent 和浏览器 headers 是否需要更新。

------

## 九、完整流程速查

```
1. 本地开发 → 微信开发者工具模拟器测试
2. 购买腾讯云服务器 → 部署后端 → 配置 nginx + HTTPS
3. 购买域名 → DNS 解析 → 申请 SSL 证书
4. 提交 ICP 备案（等待 7-20 天）
5. 备案通过 → app.js 切换域名 → 微信后台加白名单
6. 上传小程序 → 体验版测试 → 提交审核 → 发布
```
