# NHC 卫健委政策文件速查 — 项目结构文档

> 国家卫健委（NHC）规范性文件及政策解读的采集、AI 摘要、检索与浏览系统

---

## 目录

1. [项目概览](#1-项目概览)
2. [技术栈](#2-技术栈)
3. [目录结构](#3-目录结构)
4. [系统架构](#4-系统架构)
5. [后端架构](#5-后端架构)
6. [前端架构（小程序）](#6-前端架构小程序)
7. [数据流](#7-数据流)
8. [页面路由与组件树](#8-页面路由与组件树)
9. [API 接口设计](#9-api-接口设计)
10. [数据库设计](#10-数据库设计)
11. [关键设计决策](#11-关键设计决策)

---

## 1. 项目概览

### 1.1 项目定位

一个面向医疗从业者的**政策文件快速查阅工具**，自动抓取国家卫健委官网的规范性文件和政策解读，通过 AI 大模型自动提取关键要点并分类，提供微信小程序端的浏览、搜索、收藏功能。

### 1.2 核心功能

| 功能 | 说明 |
|------|------|
| 🔄 自动抓取 | 定时从 NHC 官网抓取规范性文件 + 政策解读 |
| 🤖 AI 摘要 | DeepSeek 大模型自动提取 3-5 个关键要点 |
| 🏷️ 智能分类 | AI 自动归类到 8 大医疗政策领域 |
| 🔍 搜索检索 | 关键词搜索 + AI 智能检索 Agent |
| ⭐ 收藏管理 | 本地缓存收藏，支持收藏/取消 |
| 📱 小程序端 | 微信小程序，支持上滑加载、下拉刷新、右滑返回 |

### 1.3 用户角色

当前版本为**单用户模式**，无登录/注册系统。所有用户共享同一份数据，收藏存储在本地手机缓存中。

---

## 2. 技术栈

### 2.1 后端

| 技术 | 用途 | 版本 |
|------|------|------|
| Python | 编程语言 | 3.10+ |
| FastAPI | Web 框架 | 最新 |
| SQLAlchemy | ORM 数据库操作 | 2.x |
| SQLite | 轻量级数据库 | — |
| Playwright | 无头浏览器爬虫（Firefox） | 最新 |
| APScheduler | 定时任务调度 | 最新 |
| httpx | HTTP 客户端（AI API 调用） | 最新 |
| Pydantic | 数据验证和序列化 | 2.x |

### 2.2 AI 服务

| 服务 | 模型 | 用途 |
|------|------|------|
| DeepSeek API | deepseek-v4-pro | 政策文件摘要 + 分类 + 智能检索 Agent |

### 2.3 前端（微信小程序）

| 技术 | 说明 |
|------|------|
| WXML | 微信模板语言（类似 HTML） |
| WXSS | 微信样式语言（类似 CSS，支持 rpx） |
| JavaScript (ES6) | 页面逻辑 |
| 自定义组件 | file-card、skeleton |
| 本地存储 | wx.getStorageSync / wx.setStorageSync |

---

## 3. 目录结构

```
XcxProject/
├── backend/                        # 后端 Python 服务
│   ├── main.py                     # FastAPI 应用入口，路由注册，启动事件
│   ├── config.py                   # 全局配置（数据库、AI、爬虫参数）
│   ├── database.py                 # SQLAlchemy 引擎/会话/基类
│   ├── models.py                   # ORM 数据模型（Document, Favorite）
│   ├── schemas.py                  # Pydantic 请求/响应 Schema
│   ├── nhc_policy.db               # SQLite 数据库文件
│   ├── test.py                     # 测试文件（空）
│   ├── api/                        # API 路由模块
│   │   ├── __init__.py
│   │   ├── documents.py            # 文件查询 API（列表/搜索/详情/分类）
│   │   └── favorites.py            # 收藏管理 API（增/删/查）
│   └── services/                   # 业务逻辑模块
│       ├── __init__.py
│       ├── scheduler.py            # 定时抓取调度器（APScheduler）
│       ├── scraper.py              # NHC 官网爬虫（Playwright）
│       ├── summary.py              # AI 摘要 + 分类（DeepSeek API）
│       └── agent.py                # 智能检索 Agent（ReAct 四步流程）
│
├── miniprogram/                    # 微信小程序前端
│   ├── app.js                      # 小程序入口，全局数据
│   ├── app.json                    # 小程序配置（页面路由、窗口样式）
│   ├── app.wxss                    # 全局样式（CSS 变量、基础样式）
│   ├── project.config.json         # 微信开发者工具项目配置
│   ├── sitemap.json                # 站点地图（微信 SEO）
│   ├── utils/                      # 工具函数
│   │   ├── api.js                  # 后端 API 请求封装（wx.request）
│   │   ├── storage.js              # 本地存储封装（收藏管理）
│   │   └── swipe-back.js           # 右滑返回手势 Mixin
│   ├── components/                 # 可复用自定义组件
│   │   ├── file-card/              # 文件卡片组件
│   │   │   ├── file-card.js        # 组件逻辑
│   │   │   ├── file-card.json      # 组件配置
│   │   │   ├── file-card.wxml      # 组件模板
│   │   │   └── file-card.wxss      # 组件样式
│   │   └── skeleton/               # 骨架屏加载组件
│   │       ├── skeleton.js
│   │       ├── skeleton.json
│   │       ├── skeleton.wxml
│   │       └── skeleton.wxss
│   └── pages/                      # 页面
│       ├── index/                  # 首页（文件列表 + 筛选）
│       │   ├── index.js
│       │   ├── index.json
│       │   ├── index.wxml
│       │   └── index.wxss
│       ├── detail/                 # 文件详情页
│       │   ├── detail.js
│       │   ├── detail.json
│       │   ├── detail.wxml
│       │   └── detail.wxss
│       ├── category/               # 分类列表页
│       │   ├── category.js
│       │   ├── category.json
│       │   ├── category.wxml
│       │   └── category.wxss
│       ├── search/                 # 搜索页
│       │   ├── search.js
│       │   ├── search.json
│       │   ├── search.wxml
│       │   └── search.wxss
│       ├── favorites/              # 收藏页
│       │   ├── favorites.js
│       │   ├── favorites.json
│       │   ├── favorites.wxml
│       │   └── favorites.wxss
│       └── plaintext/              # 原文纯文本阅读页
│           ├── plaintext.js
│           ├── plaintext.json
│           ├── plaintext.wxml
│           └── plaintext.wxss
│
├── GUIDE.md                        # 部署和开发指南
├── TODO.md                         # 待办事项
├── PROJECT_STRUCTURE.md            # 本文件：项目结构文档
└── NHC_规范性文件_2026年4月后.md   # 数据示例/Markdown 导出
```

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        微信小程序客户端                           │
│  ┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐ ┌─────────┐  │
│  │  首页   │ │ 搜索页   │ │ 详情页  │ │ 分类页   │ │ 收藏页  │  │
│  └───┬────┘ └────┬─────┘ └───┬────┘ └────┬─────┘ └────┬────┘  │
│      │           │           │           │             │         │
│      └───────────┴───────────┴───────────┴─────────────┘         │
│                              │  wx.request                       │
│                    本地缓存 (Storage)                             │
└──────────────────────────────┼──────────────────────────────────┘
                               │ HTTP (CORS)
┌──────────────────────────────┼──────────────────────────────────┐
│                    FastAPI 后端服务                               │
│                              ▼                                    │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                    API 路由层                          │       │
│  │  /api/v1/documents/*    /api/v1/favorites/*           │       │
│  └──────────┬───────────────────────────────┬───────────┘       │
│             │                               │                    │
│  ┌──────────▼──────────┐    ┌──────────────▼──────────────┐    │
│  │    SQLAlchemy ORM    │    │      Services 服务层         │    │
│  │    models.py         │    │  scheduler / scraper         │    │
│  │    schemas.py        │    │  summary / agent             │    │
│  └──────────┬───────────┘    └──────┬──────────┬───────────┘    │
│             │                        │          │                │
│  ┌──────────▼───────────┐  ┌────────▼──┐ ┌────▼───────────┐   │
│  │   SQLite 数据库       │  │ Playwright │ │ DeepSeek API   │   │
│  │   nhc_policy.db       │  │ NHC 爬虫   │ │ AI 摘要/检索   │   │
│  └──────────────────────┘  └───────────┘ └────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.1 请求流程

```
用户操作 → 小程序页面 → api.js (wx.request) → HTTP 请求
  → FastAPI 路由 → SessionLocal 获取 DB 会话
    → SQLAlchemy 查询 → 返回 ORM 对象
  → Pydantic Schema 序列化 → JSON 响应
→ 小程序接收 → setData 更新视图
```

### 4.2 定时抓取流程

```
APScheduler (每 N 小时)
  → asyncio.run(run_scrape_pipeline())
    → Playwright 打开 Firefox 无头浏览器
      → 访问 NHC 列表页 → 逐页抓取文件元信息
      → 逐条处理：
        ① 按 URL 去重（已存在则跳过）
        ② 抓取详情页正文
        ③ 调用 DeepSeek API → 提取要点 + 分类
        ④ 写入 SQLite
    → 提交事务
```

---

## 5. 后端架构

### 5.1 分层设计

```
┌────────────────────────────────────────┐
│  main.py          — 应用入口/路由注册    │  入口层
├────────────────────────────────────────┤
│  api/             — API 路由处理        │  路由层
├────────────────────────────────────────┤
│  services/        — 业务逻辑模块        │  服务层
├────────────────────────────────────────┤
│  models.py        — ORM 数据模型        │  数据层
│  schemas.py       — Pydantic Schema     │
│  database.py      — 数据库连接          │
├────────────────────────────────────────┤
│  config.py        — 全局配置            │  配置层
└────────────────────────────────────────┘
```

### 5.2 模块职责

#### `main.py` — 应用入口
- 创建 FastAPI 实例
- 配置 CORS 中间件（允许小程序跨域）
- 自动建表：`Base.metadata.create_all(bind=engine)`
- 注册路由：`documents_router` + `favorites_router`
- 启动事件：调用 `start_scheduler()` 启动定时任务

#### `config.py` — 全局配置
- `DATABASE_URL`: SQLite 数据库路径
- `DEEPSEEK_*`: DeepSeek AI API 配置
- `SCRAPER_INTERVAL_HOURS`: 定时抓取间隔（默认 6 小时）
- `SUMMARY_MAX_TOKENS`: AI 摘要最大 token 数（800）

#### `database.py` — 数据库连接
- **engine**: SQLAlchemy 引擎，连接 SQLite
- **SessionLocal**: 会话工厂，每次 API 调用创建独立会话
- **Base**: ORM 基类，所有模型继承此类
- `check_same_thread=False`: SQLite 多线程必需的参数

#### `models.py` — ORM 数据模型
- **Document**: 政策文件表（12 个字段 + 3 个索引）
- **Favorite**: 收藏表（3 个字段）

#### `schemas.py` — Pydantic Schema
- **DocumentItem**: 单文件响应格式（`from_attributes=True`）
- **DocumentListResponse**: 列表响应（含分页信息）
- **SearchResponse**: 搜索响应（继承列表 + query 字段）
- **LatestUpdateResponse**: 最新更新时间响应
- **FavoriteCreate**: 收藏请求体

#### `api/documents.py` — 文件查询 API
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/documents/categories` | GET | 获取所有分类 |
| `/api/v1/documents` | GET | 分页列表（支持 category/doc_type 筛选） |
| `/api/v1/documents/search` | GET | 关键词搜索（标题 + 发文机关） |
| `/api/v1/documents/latest-update` | GET | 最新入库时间 |
| `/api/v1/documents/{id}` | GET | 文件详情 |

#### `api/favorites.py` — 收藏 API
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/favorites` | GET | 收藏列表 |
| `/api/v1/favorites` | POST | 添加收藏 `{doc_id}` |
| `/api/v1/favorites/{id}` | DELETE | 取消收藏 |

#### `services/scheduler.py` — 定时调度器
- 使用 APScheduler `BackgroundScheduler`（后台线程）
- `run_scrape_pipeline()`: 核心抓取流水线
  - 冷启动抓 3 页，增量抓 1 页
  - URL 去重 → 详情抓取 → AI 摘要 → 入库
- `start_scheduler()`: 启动调度器（在 `main.py` 的 startup 事件中调用）

#### `services/scraper.py` — NHC 爬虫
- **技术选型**: Playwright + Firefox 无头浏览器
- **原因**: NHC 有 WZWS WAF + JS 动态渲染分页
- `SOURCE_URLS`: 两个来源（规范性文件 + 政策解读）
- `fetch_document_list(num_pages)`: 抓取列表页
- `fetch_document_detail(url)`: 抓取详情页（多选择器降级策略）
- 自动处理相对路径、提取附件

#### `services/summary.py` — AI 摘要服务
- 调用 DeepSeek API（Chat Completions，兼容 OpenAI 格式）
- **8 大分类**：
  1. 综合与健康促进
  2. 医疗机构与执业人员管理
  3. 医疗服务与质量安全
  4. 疾病预防控制与公共卫生
  5. 妇幼健康与人口发展
  6. 中医药与民族医药
  7. 卫生监督与行政执法
  8. 卫生信息化与标准
- 输入截取前 8000 字符，输出限制 800 token
- 分类名校验防止 AI 幻觉

#### `services/agent.py` — 智能检索 Agent
- **架构**: ReAct Loop（理解 → 搜索 → 评估 → 回答）
- **Step 1**: LLM 理解自然语言查询，提取结构化参数
- **Step 2**: SQL 组合查询（keyword LIKE + category + doc_type）
- **Step 3**: LLM 打分排序（0-10 分，≥ 5 分保留）
- **Step 4**: LLM 生成带引用的自然语言回答（200 字内）
- **单例模式**: `agent_service = AgentService()`

---

## 6. 前端架构（小程序）

### 6.1 页面层级

```
app.js (全局入口)
  ├── pages/index/index       # 首页（默认首页，Tab 形式）
  │   ├── components/file-card   # 文件卡片
  │   └── components/skeleton    # 骨架屏
  ├── pages/detail/detail     # 文件详情
  │   └── pages/plaintext/plaintext  # 纯文本原文
  ├── pages/search/search     # 搜索页
  ├── pages/category/category # 分类列表页
  └── pages/favorites/favorites # 收藏页
```

### 6.2 全局文件

#### `app.js`
- `onLaunch()`: 启动时读取本地缓存的收藏列表
- `globalData.API_BASE`: 后端 API 基础地址
- `globalData.favorites`: 全局收藏列表

#### `app.json`
- `pages`: 页面路由注册（数组顺序 = 小程序 Tab 顺序）
- `window`: 导航栏样式配置（标题、背景色、文字色）
- `lazyCodeLoading`: 按需加载组件代码

#### `app.wxss`
- 定义 CSS 变量：`--primary`, `--bg`, `--text`, `--border` 等
- 全局字体：PingFang SC（苹果中文默认字体）

### 6.3 工具函数

#### `utils/api.js`
- `request(path, options)`: 通用 wx.request 封装（返回 Promise）
- 自动过滤空查询参数
- 统一 2xx 状态码校验
- 导出 5 个 API 方法：`getDocuments`, `getDocumentDetail`, `searchDocuments`, `getLatestUpdate`, `getCategories`

#### `utils/storage.js`
- 基于 `wx.getStorageSync` / `wx.setStorageSync` 的收藏管理
- `getFavorites()`: 读取收藏列表
- `toggleFavorite(doc)`: 切换收藏状态（收藏 ∪ 取消）
- `isFavorited(docId)`: 判断是否已收藏

#### `utils/swipe-back.js`
- Mixin 模式实现的右滑返回手势
- 判定：右滑 > 80px 且 水平 > 垂直×2
- 使用 `.call(this)` 绑定页面实例

### 6.4 自定义组件

#### `file-card` — 文件卡片
- **属性**: `doc` (Object) — 文件信息对象
- **事件**: 点击 → 跳转详情页
- **展示**: 标题（2 行省略）+ 发文字号 + 日期
- **使用场景**: 首页 / 搜索 / 分类 / 收藏（4 个页面复用）

#### `skeleton` — 骨架屏
- **属性**: `count` (Number) — 占位块数量
- **展示**: 灰色矩形条（80% 宽 + 40% 宽）
- **使用场景**: 首页加载中

---

## 7. 数据流

### 7.1 文件列表加载流程

```
index.js: onShow()
  → setData({ page: 1, documents: [], loading: true })
  → api.getDocuments({ category, doc_type, page, page_size: 20 })
    → wx.request GET /api/v1/documents?category=...&doc_type=...&page=1&page_size=20
    → FastAPI: list_documents() → DB 查询 → DocumentListResponse
    → 返回 JSON { items: [...], total: N, page: 1, page_size: 20 }
  → setData({ documents: [...], loading: false, hasMore: ... })
  → WXML 自动重渲染：<file-card wx:for="{{documents}}" />
```

### 7.2 收藏流程

```
detail.js: toggleFav()
  → storage.toggleFavorite(doc) → 读写 wx.Storage
  → setData({ isFav: true/false })
  → WXML: {{isFav ? '★' : '☆'}}
  → wx.showToast('已加入收藏' / '已取消收藏')
```

### 7.3 抓取入库流程

```
scheduler.py: run_scrape_pipeline()
  → scraper.fetch_document_list(3) → [{title, url, publish_date, doc_type}, ...]
  → for each item:
      → 去重 (by url)
      → scraper.fetch_document_detail(url) → {content, attachments}
      → summary.extract_key_points(content) → (points, category)
      → Document(...) → db.add()
  → db.commit()
```

---

## 8. 页面路由与组件树

### 8.1 路由表

| 路径 | 页面 | 参数 | 进入方式 |
|------|------|------|----------|
| `pages/index/index` | 首页 | — | 默认首页 |
| `pages/detail/detail` | 详情页 | `id` | 点击文件卡片 |
| `pages/search/search` | 搜索页 | — | 首页搜索框 |
| `pages/category/category` | 分类页 | `category`, `doc_type` | 首页"查看更多" |
| `pages/favorites/favorites` | 收藏页 | — | 首页收藏按钮 |
| `pages/plaintext/plaintext` | 原文页 | `id` | 详情页"查看原文" |

### 8.2 页面跳转图

```
                        ┌─────────────┐
                        │   首页 Index  │
                        └──┬───┬───┬──┘
              ┌────────────┤   │   ├────────────┐
              ▼            ▼   │   ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ 搜索页    │ │ 分类页    │ │ 详情页    │ │ 收藏页    │
        │ Search   │ │ Category │ │ Detail   │ │ Favorites│
        └──────────┘ └──────────┘ └────┬─────┘ └──────────┘
              │              │         │
              └──────────────┴────┐    │
                                 ▼    ▼
                          ┌──────────────┐
                          │ 文件卡片组件   │
                          │ file-card    │
                          └──────────────┘
                                 │
                                 ▼
                          ┌──────────────┐
                          │ 原文页        │
                          │ plaintext    │
                          └──────────────┘
```

### 8.3 组件引用关系

```
index.json:
  "file-card": "/components/file-card/file-card"      ← 文件卡片
  "skeleton": "/components/skeleton/skeleton"          ← 骨架屏

category.json:
  "file-card": "/components/file-card/file-card"

search.json:
  "file-card": "/components/file-card/file-card"

favorites.json:
  "file-card": "/components/file-card/file-card"
```

---

## 9. API 接口设计

### 9.1 接口总览

| 序号 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 1 | GET | `/api/v1/documents/categories` | 获取分类列表 |
| 2 | GET | `/api/v1/documents` | 分页文件列表 |
| 3 | GET | `/api/v1/documents/search` | 关键词搜索 |
| 4 | GET | `/api/v1/documents/latest-update` | 最新更新时间 |
| 5 | GET | `/api/v1/documents/{id}` | 文件详情 |
| 6 | GET | `/api/v1/favorites` | 收藏列表 |
| 7 | POST | `/api/v1/favorites` | 添加收藏 |
| 8 | DELETE | `/api/v1/favorites/{id}` | 取消收藏 |

### 9.2 请求/响应示例

#### GET /api/v1/documents?category=疾病预防控制与公共卫生&page=1&page_size=20

```json
// 响应
{
  "items": [
    {
      "id": 1,
      "title": "关于印发《传染病防治管理办法》的通知",
      "doc_number": "国卫办发〔2024〕15号",
      "issuing_authority": "国家卫生健康委",
      "publish_date": "2024-06-01",
      "category": "疾病预防控制与公共卫生",
      "doc_type": "规范性文件",
      "original_url": "https://www.nhc.gov.cn/...",
      "content": "",
      "summary": "[\"要点一\", \"要点二\", \"要点三\"]",
      "attachments": "[{\"name\":\"附件1.pdf\",\"url\":\"...\"}]"
    }
  ],
  "total": 156,
  "page": 1,
  "page_size": 20
}
```

#### GET /api/v1/documents/search?q=传染病&page=1

```json
{
  "items": [...],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "query": "传染病"
}
```

#### POST /api/v1/favorites

```json
// 请求体
{ "doc_id": 123 }

// 响应
{ "status": "ok" }
```

---

## 10. 数据库设计

### 10.1 ER 图

```
┌─────────────────────────────────────────┐
│               documents                   │
├─────────────────────────────────────────┤
│ PK  id              INTEGER (自增)       │
│     title           VARCHAR(500) NOT NULL│
│     doc_number      VARCHAR(100)         │
│     issuing_authority VARCHAR(200)       │
│     publish_date    VARCHAR(20) NOT NULL │
│     category        VARCHAR(100) NOT NULL│
│     doc_type        VARCHAR(100) NOT NULL│
│     original_url    VARCHAR(500) NOT NULL│
│     content         TEXT                 │
│     summary         TEXT (JSON)          │
│     attachments     TEXT (JSON)          │
│     created_at      VARCHAR(20)          │
│                                          │
│ IDX: idx_publish_date                    │
│ IDX: idx_category                        │
│ IDX: idx_doc_type                        │
└──────────────┬──────────────────────────┘
               │
               │ doc_id (外键逻辑关联)
               │
┌──────────────▼──────────────────────────┐
│               favorites                   │
├─────────────────────────────────────────┤
│ PK  id              INTEGER (自增)       │
│     doc_id          INTEGER NOT NULL     │
│     created_at      VARCHAR(20)          │
└─────────────────────────────────────────┘
```

### 10.2 索引策略

| 索引名 | 字段 | 用途 |
|--------|------|------|
| `idx_publish_date` | `publish_date` | 列表按日期降序排列 |
| `idx_category` | `category` | 按分类筛选 |
| `idx_doc_type` | `doc_type` | 按文件类型筛选 |

### 10.3 字段设计说明

- **publish_date 用 VARCHAR 而非 DATE**: NHC 网站的日期格式不统一（有的只有年月），且 SQLite 对日期类型支持有限
- **summary 存 JSON 字符串**: AI 提取的要点以 JSON 数组存储，前端 `JSON.parse()` 后渲染
- **attachments 存 JSON 字符串**: `[{"name": "附件名", "url": "下载链接"}]`
- **created_at 存 ISO 格式字符串**: `lambda: datetime.now().isoformat()`

---

## 11. 关键设计决策

### 11.1 为什么用 Playwright 而不是 requests？

NHC 卫健委官网有 WZWS WAF（Web 应用防火墙），纯 HTTP 请求会被拦截。Playwright 启动真实 Firefox 浏览器，能完整模拟浏览器指纹（User-Agent、Sec-Fetch 头等），并且可以执行页面中的 JavaScript（分页组件 `createPageHTML` 由 JS 动态生成）。

### 11.2 为什么用 SQLite 而不是 MySQL/PostgreSQL？

- **零配置**: 无需安装数据库服务，一个文件即用
- **便携**: 数据库文件 `nhc_policy.db` 可以直接复制迁移
- **够用**: 政策文件数量级在数千条以内，SQLite 的并发能力完全胜任
- **注意**: `check_same_thread=False` 是 FastAPI 异步框架中使用 SQLite 的必需配置

### 11.3 为什么分类用 AI 而不是规则匹配？

政策文件标题格式多样，仅靠关键词规则（如 `if '传染病' in title`）容易误判或漏判。DeepSeek 等大模型能理解文件内容的语义，分类准确率更高。同时将分类和摘要合并在一次 API 调用中完成，节省费用。

### 11.4 为什么收藏用本地存储而不是服务端？

当前版本无用户登录系统，无法区分不同用户的收藏。本地存储（wx.Storage）是微信小程序原生的数据持久化方案，无需网络请求，即时响应。

### 11.5 为什么前端不分包？

项目页面数量较少（6 个页面），总体积远未达到微信小程序 2MB 的包大小限制，不需要分包加载。`lazyCodeLoading: "requiredComponents"` 开启了组件按需注入，可优化首屏加载速度。

### 11.6 Agent 检索 vs 关键词搜索

系统提供了两种检索方式：

| 特性 | 关键词搜索 (api.js) | Agent 检索 (agent.py) |
|------|---------------------|----------------------|
| 原理 | SQL LIKE 模糊匹配 | LLM 理解 + SQL 组合 + LLM 评估 |
| 速度 | 快（毫秒级） | 慢（秒级，需多次 LLM 调用） |
| 准确度 | 依赖关键词匹配 | 理解语义，更准确 |
| 输出 | 文件列表 | 自然语言回答 + 文件列表 |
| 使用 | 搜索页直接使用 | 通过 agent_service.search() |

---

## 附录

### A. 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DEEPSEEK_API_KEY` | `""` | DeepSeek API 密钥 |
| `SCRAPER_INTERVAL_HOURS` | `6` | 定时抓取间隔（小时） |

### B. 启动命令

```bash
# 后端
cd backend
pip install -r requirements.txt
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8000

# 小程序
# 用微信开发者工具打开 miniprogram/ 目录
```

### C. 文件数量统计

| 层级 | 文件数 | 代码行数（约） |
|------|--------|---------------|
| 后端 Python | 11 | ~900 |
| 小程序 JS | 12 | ~500 |
| 小程序 WXML | 7 | ~160 |
| 小程序 WXSS | 8 | ~250 |
| **合计** | **~38** | **~1810** |
