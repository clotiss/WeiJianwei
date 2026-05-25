# 国家卫健委政策文件微信小程序 — 实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个微信小程序，从 NHC 官网抓取政策文件，提供分类浏览、关键词搜索、AI 关键内容提取、收藏和每日推送功能。

**Architecture:** Python FastAPI 后端（Playwright 抓取 + SQLite 存储 + DeepSeek API 摘要），微信小程序原生前端（wx.request 通信 + wx.setStorageSync 本地缓存）。前后端通过 RESTful JSON API 交互。

**Tech Stack:** Python 3.12+, FastAPI, SQLite (SQLAlchemy), Playwright, DeepSeek API, 微信原生框架

---

## 文件结构

```
/Users/hulei/Documents/test/
├── backend/
│   ├── main.py                 # FastAPI 入口，CORS 配置
│   ├── requirements.txt
│   ├── config.py               # 数据库路径、Claude API key 等配置
│   ├── models.py               # SQLAlchemy 模型
│   ├── database.py             # 数据库连接和初始化
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── api/
│   │   ├── __init__.py
│   │   ├── documents.py        # 文件列表、详情、搜索、最近更新
│   │   └── favorites.py        # 收藏增删查
│   ├── services/
│   │   ├── __init__.py
│   │   ├── scraper.py          # Playwright NHC 抓取
│   │   ├── summary.py          # Claude API 关键内容提取
│   │   └── scheduler.py        # APScheduler 定时抓取
│   └── tests/
│       ├── test_api.py
│       └── test_scraper.py
├── miniprogram/
│   ├── app.js
│   ├── app.json
│   ├── app.wxss
│   ├── project.config.json
│   ├── pages/
│   │   ├── index/              # 首页
│   │   │   ├── index.js
│   │   │   ├── index.json
│   │   │   ├── index.wxml
│   │   │   └── index.wxss
│   │   ├── category/           # 分类列表页
│   │   │   ├── category.js
│   │   │   ├── category.json
│   │   │   ├── category.wxml
│   │   │   └── category.wxss
│   │   ├── detail/             # 详情页
│   │   │   ├── detail.js
│   │   │   ├── detail.json
│   │   │   ├── detail.wxml
│   │   │   └── detail.wxss
│   │   ├── search/             # 搜索页
│   │   │   ├── search.js
│   │   │   ├── search.json
│   │   │   ├── search.wxml
│   │   │   └── search.wxss
│   │   └── favorites/          # 收藏页
│   │       ├── favorites.js
│   │       ├── favorites.json
│   │       ├── favorites.wxml
│   │       └── favorites.wxss
│   ├── components/
│   │   ├── file-card/          # 文件卡片（列表页复用）
│   │   │   ├── file-card.js
│   │   │   ├── file-card.json
│   │   │   ├── file-card.wxml
│   │   │   └── file-card.wxss
│   │   └── skeleton/           # 骨架屏（加载占位）
│   │       ├── skeleton.js
│   │       ├── skeleton.json
│   │       ├── skeleton.wxml
│   │       └── skeleton.wxss
│   └── utils/
│       ├── api.js              # wx.request 封装
│       └── storage.js          # 本地缓存 + 收藏管理
└── docs/
    └── superpowers/
        ├── specs/2026-05-25-nhc-miniprogram-design.md
        └── plans/ (this file)
```

---

## 数据库设计

```sql
-- documents 表
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    doc_number TEXT,                          -- 文号，如"国卫医发〔2026〕12号"
    issuing_authority TEXT DEFAULT '国家卫生健康委',
    publish_date TEXT NOT NULL,               -- ISO 格式 YYYY-MM-DD
    category TEXT NOT NULL,                   -- 一级分类：医政管理/疾控/妇幼健康/...
    doc_type TEXT NOT NULL,                   -- 二级分类：规范性文件/政策解读/通知公告
    original_url TEXT NOT NULL,               -- NHC 原文链接
    summary TEXT,                             -- AI 生成的关键内容提取
    attachments TEXT,                         -- JSON 数组：[{"name":"...","url":"..."}]
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_documents_publish_date ON documents(publish_date DESC);
CREATE INDEX idx_documents_category ON documents(category);
CREATE INDEX idx_documents_doc_type ON documents(doc_type);

-- favorites 表（MVP 阶段用本地存储，后期可迁移至此）
CREATE TABLE favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES documents(id),
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## API 设计

所有接口前缀 `/api/v1`，返回 JSON。

### 获取文件列表
```
GET /api/v1/documents?category=&doc_type=&page=1&page_size=20
Response: { items: [...], total: 47, page: 1, page_size: 20 }
```

### 获取文件详情
```
GET /api/v1/documents/{id}
Response: { id, title, doc_number, issuing_authority, publish_date, category, doc_type, original_url, summary, attachments, created_at }
```

### 搜索文件
```
GET /api/v1/documents/search?q=感染防控&page=1&page_size=20
Response: { items: [...], total: 12, page: 1, page_size: 20, query: "感染防控" }
```

### 最近更新时间
```
GET /api/v1/documents/latest-update
Response: { latest_update: "2026-05-25T10:30:00" }
```

### 收藏操作（前端本地存储为主，保留后端接口备用）
```
GET    /api/v1/favorites                  # 获取收藏列表
POST   /api/v1/favorites                  # 添加收藏 { doc_id: 1 }
DELETE /api/v1/favorites/{doc_id}         # 取消收藏
```

---

## Phase 1: 后端基础

### Task 1: 项目初始化

**Files:**
- Create: `backend/config.py`
- Create: `backend/requirements.txt`
- Create: `backend/database.py`

- [ ] **Step 1: 创建 requirements.txt**

```
fastapi==0.115.0
uvicorn==0.31.0
sqlalchemy==2.0.35
pydantic==2.9.0
playwright==1.47.0
apscheduler==3.10.4
httpx==0.27.0
pytest==8.3.0
```

- [ ] **Step 2: 创建 config.py**

```python
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'nhc_policy.db')}"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

SCRAPER_INTERVAL_HOURS = int(os.getenv("SCRAPER_INTERVAL_HOURS", "6"))
SCRAPER_TARGET_URL = "http://www.nhc.gov.cn/wjw/gfxwj/list.shtml"

SUMMARY_MAX_TOKENS = 500
```

- [ ] **Step 3: 创建 database.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
```

- [ ] **Step 4: 验证**

```bash
cd /Users/hulei/Documents/test/backend && python3 -c "from database import engine; print('ok')"
```

---

### Task 2: 数据模型与建表

**Files:**
- Create: `backend/models.py`
- Create: `backend/schemas.py`

- [ ] **Step 1: 创建 models.py**

```python
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Index
from database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    doc_number = Column(String(100))
    issuing_authority = Column(String(200), default="国家卫生健康委")
    publish_date = Column(String(20), nullable=False)
    category = Column(String(100), nullable=False)
    doc_type = Column(String(100), nullable=False)
    original_url = Column(String(500), nullable=False)
    summary = Column(Text)
    attachments = Column(Text)  # JSON string
    created_at = Column(String(20), default=lambda: datetime.now().isoformat())

    __table_args__ = (
        Index("idx_publish_date", "publish_date"),
        Index("idx_category", "category"),
        Index("idx_doc_type", "doc_type"),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, nullable=False)
    created_at = Column(String(20), default=lambda: datetime.now().isoformat())
```

- [ ] **Step 2: 创建 schemas.py**

```python
from pydantic import BaseModel
from typing import Optional


class DocumentItem(BaseModel):
    id: int
    title: str
    doc_number: Optional[str] = ""
    issuing_authority: Optional[str] = ""
    publish_date: str
    category: str
    doc_type: str
    original_url: Optional[str] = ""
    summary: Optional[str] = ""
    attachments: Optional[str] = "[]"

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int
    page: int
    page_size: int


class SearchResponse(DocumentListResponse):
    query: str


class LatestUpdateResponse(BaseModel):
    latest_update: Optional[str]


class FavoriteCreate(BaseModel):
    doc_id: int
```

- [ ] **Step 3: 初始化建表**

```bash
cd /Users/hulei/Documents/test/backend && python3 -c "
from database import engine, Base
from models import Document, Favorite
Base.metadata.create_all(bind=engine)
print('Tables created')
"
```

---

### Task 3: FastAPI 入口 + 文件列表/详情/搜索 API

**Files:**
- Create: `backend/main.py`
- Create: `backend/api/__init__.py`
- Create: `backend/api/documents.py`

- [ ] **Step 1: 创建 api/documents.py**

```python
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import desc, or_
from database import SessionLocal
from models import Document
from schemas import DocumentItem, DocumentListResponse, SearchResponse, LatestUpdateResponse

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.get("", response_model=DocumentListResponse)
def list_documents(
    category: str = Query(default=""),
    doc_type: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    db = SessionLocal()
    try:
        q = db.query(Document)
        if category and category != "全部":
            q = q.filter(Document.category == category)
        if doc_type and doc_type != "全部类型":
            q = q.filter(Document.doc_type == doc_type)
        total = q.count()
        items = (
            q.order_by(desc(Document.publish_date))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return DocumentListResponse(
            items=[DocumentItem.model_validate(d) for d in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    finally:
        db.close()


@router.get("/search", response_model=SearchResponse)
def search_documents(
    q: str = Query(default="", alias="q"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    db = SessionLocal()
    try:
        query = db.query(Document).filter(
            or_(
                Document.title.contains(q),
                Document.issuing_authority.contains(q),
            )
        )
        total = query.count()
        items = (
            query.order_by(desc(Document.publish_date))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return SearchResponse(
            items=[DocumentItem.model_validate(d) for d in items],
            total=total,
            page=page,
            page_size=page_size,
            query=q,
        )
    finally:
        db.close()


@router.get("/latest-update", response_model=LatestUpdateResponse)
def latest_update():
    db = SessionLocal()
    try:
        doc = db.query(Document).order_by(desc(Document.created_at)).first()
        return LatestUpdateResponse(latest_update=doc.created_at if doc else None)
    finally:
        db.close()


@router.get("/{doc_id}", response_model=DocumentItem)
def get_document(doc_id: int):
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentItem.model_validate(doc)
    finally:
        db.close()
```

- [ ] **Step 2: 创建 api/__init__.py** (空文件)

```bash
touch /Users/hulei/Documents/test/backend/api/__init__.py
```

- [ ] **Step 3: 创建 main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from models import Document, Favorite
from api.documents import router as documents_router
from api.favorites import router as favorites_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="NHC Policy API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(favorites_router)
```

- [ ] **Step 4: 启动验证**

```bash
cd /Users/hulei/Documents/test/backend && \
  python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 2
curl -s http://localhost:8000/api/v1/documents?page=1 | python3 -m json.tool
```

---

### Task 4: 收藏 API

**Files:**
- Create: `backend/api/favorites.py`

- [ ] **Step 1: 创建 api/favorites.py**

```python
from fastapi import APIRouter, HTTPException
from database import SessionLocal
from models import Favorite, Document
from schemas import FavoriteCreate, DocumentItem

router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])


@router.get("")
def list_favorites():
    db = SessionLocal()
    try:
        favs = db.query(Favorite).order_by(Favorite.created_at.desc()).all()
        items = []
        for f in favs:
            doc = db.query(Document).filter(Document.id == f.doc_id).first()
            if doc:
                items.append(DocumentItem.model_validate(doc))
        return {"items": items, "total": len(items)}
    finally:
        db.close()


@router.post("")
def add_favorite(body: FavoriteCreate):
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == body.doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        existing = (
            db.query(Favorite).filter(Favorite.doc_id == body.doc_id).first()
        )
        if existing:
            return {"status": "already_favorited"}
        fav = Favorite(doc_id=body.doc_id)
        db.add(fav)
        db.commit()
        return {"status": "ok"}
    finally:
        db.close()


@router.delete("/{doc_id}")
def remove_favorite(doc_id: int):
    db = SessionLocal()
    try:
        fav = db.query(Favorite).filter(Favorite.doc_id == doc_id).first()
        if not fav:
            raise HTTPException(status_code=404, detail="Favorite not found")
        db.delete(fav)
        db.commit()
        return {"status": "ok"}
    finally:
        db.close()
```

- [ ] **Step 2: 验证收藏接口**

启动服务后执行：
```bash
curl -s -X POST http://localhost:8000/api/v1/favorites \
  -H "Content-Type: application/json" \
  -d '{"doc_id": 1}' | python3 -m json.tool

curl -s http://localhost:8000/api/v1/favorites | python3 -m json.tool

curl -s -X DELETE http://localhost:8000/api/v1/favorites/1
```

---

### Task 5: NHC 抓取器

**Files:**
- Create: `backend/services/__init__.py`
- Create: `backend/services/scraper.py`

- [ ] **Step 1: 创建 services/__init__.py** (空文件)

```bash
touch /Users/hulei/Documents/test/backend/services/__init__.py
```

- [ ] **Step 2: 创建 services/scraper.py**

```python
"""NHC 规范性文件列表页抓取。使用 Playwright 无头浏览器绕过 JS 反爬。"""

import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright


NHC_LIST_URL = "http://www.nhc.gov.cn/wjw/gfxwj/list.shtml"
BASE_URL = "http://www.nhc.gov.cn"


async def fetch_document_list() -> list[dict]:
    """抓取 NHC 规范性文件列表页，返回文件元信息列表。"""
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(NHC_LIST_URL, wait_until="networkidle", timeout=30000)

        # 等待列表渲染
        await page.wait_for_selector(".zxxx_list li, .listMain li", timeout=10000)

        items = await page.query_selector_all(".zxxx_list li, .listMain li")
        for item in items:
            try:
                link_el = await item.query_selector("a")
                if not link_el:
                    continue
                title = (await link_el.inner_text()).strip()
                href = await link_el.get_attribute("href")

                # 拼接完整 URL
                if href and not href.startswith("http"):
                    href = BASE_URL + href if href.startswith("/") else f"{BASE_URL}/{href}"

                # 提取日期
                date_el = await item.query_selector("span, .time, .date")
                date_str = ""
                if date_el:
                    date_str = (await date_el.inner_text()).strip()
                    date_str = re.sub(r"[\[\]]", "", date_str)

                results.append({
                    "title": title,
                    "url": href or "",
                    "publish_date": date_str or datetime.now().strftime("%Y-%m-%d"),
                })
            except Exception:
                continue

        await browser.close()
    return results


async def fetch_document_detail(url: str) -> dict:
    """抓取单篇文件详情页，返回正文内容和附件信息。"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        content = ""
        attachments = []

        try:
            content_el = await page.query_selector(".con, #content, .TRS_Editor, .article-con")
            if content_el:
                content = (await content_el.inner_text()).strip()
        except Exception:
            content = ""

        # 提取附件
        try:
            attach_els = await page.query_selector_all("a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], a[href$='.xls'], a[href$='.xlsx']")
            for a in attach_els:
                name = (await a.inner_text()).strip()
                href = await a.get_attribute("href")
                if name and href:
                    attachments.append({"name": name, "url": href})
        except Exception:
            pass

        await browser.close()
    return {"content": content, "attachments": attachments}
```

- [ ] **Step 3: 编写爬虫测试**

```bash
cd /Users/hulei/Documents/test/backend && python3 -c "
import asyncio
from services.scraper import fetch_document_list
results = asyncio.run(fetch_document_list())
print(f'Fetched {len(results)} documents')
for r in results[:3]:
    print(f'  - {r[\"title\"][:60]}...  {r[\"publish_date\"]}')
"
```

---

### Task 6: DeepSeek API 关键内容提取

**Files:**
- Create: `backend/services/summary.py`

- [ ] **Step 1: 创建 services/summary.py**

```python
"""使用 DeepSeek API 提取政策文件的关键内容要点。"""

import json
import httpx
from config import DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_BASE_URL, SUMMARY_MAX_TOKENS

SYSTEM_PROMPT = """你是一个医疗政策文件分析助手。请从以下政策文件正文中提取 3-5 个关键要点。

要求：
- 每条要点 1-2 句话，直接说明政策要求或变化
- 按重要性排序
- 输出为 JSON 数组格式：["要点一内容", "要点二内容", ...]
- 只输出 JSON，不要其他文字"""


async def extract_key_points(content: str) -> list[str]:
    """调用 DeepSeek API 提取关键内容。返回要点字符串列表。"""
    if not DEEPSEEK_API_KEY:
        return []

    # 截断过长内容
    text = content[:8000]

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "max_tokens": SUMMARY_MAX_TOKENS,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                return json.loads(raw.strip())
        except Exception:
            pass
    return []
```

---

### Task 7: 定时调度器 + 完整抓取流水线

**Files:**
- Create: `backend/services/scheduler.py`

- [ ] **Step 1: 创建 services/scheduler.py**

```python
"""定时调度：抓取 NHC → 去重入库 → AI 摘要。"""

import re
import json
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

from database import SessionLocal
from models import Document
from services.scraper import fetch_document_list, fetch_document_detail
from services.summary import extract_key_points
from config import SCRAPER_INTERVAL_HOURS

# 分类关键词映射
CATEGORY_KEYWORDS = {
    "医政管理": ["医疗机构", "医院", "医疗质量", "医疗服务", "医政", "医师", "护士", "感染防控", "医疗安全"],
    "疾控": ["疾控", "传染病", "疫苗接种", "疫情防控", "公共卫生", "疾病预防"],
    "妇幼健康": ["妇幼", "母婴", "儿童", "妇产", "出生缺陷", "两癌"],
    "基层卫生": ["基层", "社区卫生", "乡镇卫生", "村卫生", "家庭医生", "基本公卫"],
    "药政": ["药品", "药物", "基本药物", "处方", "药事", "抗菌药物", "麻精"],
    "医管": ["医保", "DRG", "DIP", "支付", "绩效考核", "评审", "医管"],
}


def classify_document(title: str) -> tuple[str, str]:
    """根据标题关键词分类，返回 (category, doc_type)。"""
    category = "其他"
    for cat_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                category = cat_name
                break
        if category != "其他":
            break

    # 二级分类
    if "通知" in title or "印发" in title or "发布" in title:
        doc_type = "通知公告"
    elif "解读" in title or "一图读懂" in title:
        doc_type = "政策解读"
    elif "办法" in title or "规范" in title or "标准" in title or "指南" in title:
        doc_type = "规范性文件"
    else:
        doc_type = "规范性文件"

    return category, doc_type


def extract_doc_number(title: str) -> str:
    """从标题中提取文号（如有）。"""
    m = re.search(r"[〔（【]\d{4}[〕）】]\d+号", title)
    return m.group(0) if m else ""


async def run_scrape_pipeline():
    """执行一次完整抓取流水线。"""
    print(f"[{datetime.now()}] Starting scrape pipeline...")
    items = await fetch_document_list()
    print(f"  Fetched {len(items)} items from NHC")

    db = SessionLocal()
    try:
        for item in items:
            # 去重（按 URL）
            existing = db.query(Document).filter(Document.original_url == item["url"]).first()
            if existing:
                continue

            # 抓详情
            detail = await fetch_document_detail(item["url"])
            content = detail.get("content", "")

            # AI 摘要
            summary_points = await extract_key_points(content)
            summary = json.dumps(summary_points, ensure_ascii=False) if summary_points else ""

            # 分类
            category, doc_type = classify_document(item["title"])
            doc_number = extract_doc_number(item["title"])

            doc = Document(
                title=item["title"],
                doc_number=doc_number,
                issuing_authority="国家卫生健康委",
                publish_date=item["publish_date"],
                category=category,
                doc_type=doc_type,
                original_url=item["url"],
                summary=summary,
                attachments=json.dumps(detail.get("attachments", []), ensure_ascii=False),
            )
            db.add(doc)
            print(f"  + {item['title'][:50]}...")
        db.commit()
    finally:
        db.close()
    print(f"[{datetime.now()}] Pipeline done.")


def start_scheduler():
    """启动后台定时调度器。"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: asyncio.run(run_scrape_pipeline()),
        "interval",
        hours=SCRAPER_INTERVAL_HOURS,
        id="nhc_scraper",
    )
    scheduler.start()
    print(f"Scheduler started, interval={SCRAPER_INTERVAL_HOURS}h")
    return scheduler
```

- [ ] **Step 2: 更新 main.py 启动调度器**

在 `main.py` 末尾添加：
```python
from services.scheduler import start_scheduler

@app.on_event("startup")
def on_startup():
    start_scheduler()
```

---

## Phase 2: 小程序前端

### Task 8: 小程序项目初始化

**Files:**
- Create: `miniprogram/app.json`
- Create: `miniprogram/app.js`
- Create: `miniprogram/app.wxss`
- Create: `miniprogram/project.config.json`

- [ ] **Step 1: 创建 project.config.json**

```json
{
  "description": "卫健委政策文件速查",
  "packOptions": { "ignore": [] },
  "setting": {
    "urlCheck": false,
    "es6": true,
    "enhance": true,
    "postcss": true,
    "minified": true
  },
  "appid": "YOUR_APPID",
  "projectname": "nhc-policy",
  "libVersion": "3.5.0"
}
```

- [ ] **Step 2: 创建 app.json**

```json
{
  "pages": [
    "pages/index/index",
    "pages/category/category",
    "pages/detail/detail",
    "pages/search/search",
    "pages/favorites/favorites"
  ],
  "window": {
    "navigationBarTitleText": "卫健委政策速查",
    "navigationBarBackgroundColor": "#1a6fb5",
    "navigationBarTextStyle": "white",
    "backgroundColor": "#f5f5f5"
  },
  "style": "v2",
  "sitemapLocation": "sitemap.json"
}
```

- [ ] **Step 3: 创建 app.js**

```javascript
App({
  onLaunch() {
    // 检查是否有缓存的收藏数据
    const favs = wx.getStorageSync('favorites') || [];
    this.globalData.favorites = favs;
  },
  globalData: {
    API_BASE: 'http://localhost:8000/api/v1',
    favorites: []
  }
});
```

- [ ] **Step 4: 创建 app.wxss**

```css
/* 全局样式变量 */
page {
  --primary: #1a6fb5;
  --primary-light: #e8f2fa;
  --text: #333333;
  --text-secondary: #888888;
  --bg: #f5f5f5;
  --white: #ffffff;
  --border: #eeeeee;

  font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
  font-size: 14px;
  color: var(--text);
  background-color: var(--bg);
}
```

---

### Task 9: API 工具函数 + 本地存储工具

**Files:**
- Create: `miniprogram/utils/api.js`
- Create: `miniprogram/utils/storage.js`

- [ ] **Step 1: 创建 utils/api.js**

```javascript
const app = getApp();

function request(path, options = {}) {
  const { method = 'GET', data, params } = options;

  let url = app.globalData.API_BASE + path;
  if (params) {
    const qs = Object.entries(params)
      .filter(([_, v]) => v !== '' && v !== undefined)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join('&');
    if (qs) url += '?' + qs;
  }

  return new Promise((resolve, reject) => {
    wx.request({
      url,
      method,
      data,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          reject(res);
        }
      },
      fail(err) {
        reject(err);
      }
    });
  });
}

module.exports = {
  getDocuments(params) {
    return request('/documents', { params });
  },
  getDocumentDetail(id) {
    return request(`/documents/${id}`);
  },
  searchDocuments(params) {
    return request('/documents/search', { params });
  },
  getLatestUpdate() {
    return request('/documents/latest-update');
  }
};
```

- [ ] **Step 2: 创建 utils/storage.js**

```javascript
const FAVORITES_KEY = 'favorites';

function getFavorites() {
  try {
    return wx.getStorageSync(FAVORITES_KEY) || [];
  } catch (e) {
    return [];
  }
}

function setFavorites(favs) {
  wx.setStorageSync(FAVORITES_KEY, favs);
}

function isFavorited(docId) {
  const favs = getFavorites();
  return favs.some(f => f.id === docId);
}

function toggleFavorite(doc) {
  let favs = getFavorites();
  const idx = favs.findIndex(f => f.id === doc.id);
  if (idx >= 0) {
    favs.splice(idx, 1);
    setFavorites(favs);
    return false; // 已取消收藏
  } else {
    favs.push(doc);
    setFavorites(favs);
    return true; // 已收藏
  }
}

module.exports = { getFavorites, setFavorites, isFavorited, toggleFavorite };
```

---

### Task 10: 文件卡片组件 + 骨架屏组件

**Files:**
- Create: `miniprogram/components/file-card/file-card.json`
- Create: `miniprogram/components/file-card/file-card.wxml`
- Create: `miniprogram/components/file-card/file-card.wxss`
- Create: `miniprogram/components/file-card/file-card.js`
- Create: `miniprogram/components/skeleton/skeleton.json`
- Create: `miniprogram/components/skeleton/skeleton.wxml`
- Create: `miniprogram/components/skeleton/skeleton.wxss`
- Create: `miniprogram/components/skeleton/skeleton.js`

- [ ] **Step 1: file-card.json**

```json
{
  "component": true,
  "usingComponents": {}
}
```

- [ ] **Step 2: file-card.wxml**

```xml
<view class="file-card" bindtap="onTap">
  <view class="title">{{doc.title}}</view>
  <view class="meta">
    <text wx:if="{{doc.doc_number}}">{{doc.doc_number}} · </text>
    <text>{{doc.publish_date}}</text>
  </view>
</view>
```

- [ ] **Step 3: file-card.wxss**

```css
.file-card {
  background: #fff;
  border: 1px solid #eee;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
}
.file-card:active { background: #f5f5f5; }
.title {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  margin-bottom: 4px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.meta {
  font-size: 12px;
  color: #999;
}
```

- [ ] **Step 4: file-card.js**

```javascript
Component({
  properties: {
    doc: { type: Object, value: {} }
  },
  methods: {
    onTap() {
      wx.navigateTo({
        url: `/pages/detail/detail?id=${this.properties.doc.id}`
      });
    }
  }
});
```

- [ ] **Step 5: skeleton.json**

```json
{
  "component": true,
  "usingComponents": {}
}
```

- [ ] **Step 6: skeleton.wxml**

```xml
<view class="skeleton">
  <view class="skeleton-block" wx:for="{{count}}" wx:key="index">
    <view class="skeleton-line w-80"></view>
    <view class="skeleton-line w-40"></view>
  </view>
</view>
```

- [ ] **Step 7: skeleton.wxss**

```css
.skeleton-block {
  background: #f0f0f0;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
}
.skeleton-line {
  height: 14px;
  background: #e0e0e0;
  border-radius: 4px;
  margin-bottom: 8px;
}
.w-80 { width: 80%; }
.w-40 { width: 40%; }
```

- [ ] **Step 8: skeleton.js**

```javascript
Component({
  properties: {
    count: { type: Number, value: 3 }
  }
});
```

---

### Task 11: 首页

**Files:**
- Create: `miniprogram/pages/index/index.json`
- Create: `miniprogram/pages/index/index.wxml`
- Create: `miniprogram/pages/index/index.wxss`
- Create: `miniprogram/pages/index/index.js`

- [ ] **Step 1: index.json**

```json
{
  "usingComponents": {
    "file-card": "/components/file-card/file-card",
    "skeleton": "/components/skeleton/skeleton"
  }
}
```

- [ ] **Step 2: index.wxml**

```xml
<view class="container">
  <!-- 顶部栏 -->
  <view class="top-bar">
    <view class="search-box" bindtap="goSearch">
      <text class="search-icon">🔍</text>
      <text class="search-placeholder">搜索标题、发文机构...</text>
    </view>
    <view class="fav-btn" bindtap="goFavorites">⭐</view>
  </view>

  <!-- 最近更新 -->
  <view class="update-time" wx:if="{{latestUpdate}}">
    🕐 最近更新：{{latestUpdate}}
  </view>

  <!-- 领域标签 -->
  <scroll-view class="category-tags" scroll-x>
    <view
      wx:for="{{categories}}"
      wx:key="*this"
      class="tag {{activeCategory === item ? 'tag-active' : ''}}"
      bindtap="onCategoryTap"
      data-category="{{item}}"
    >{{item}}</view>
  </scroll-view>

  <!-- 类型筛选 -->
  <view class="type-bar">
    <view
      wx:for="{{docTypes}}"
      wx:key="*this"
      class="type-item {{activeType === item ? 'type-active' : ''}}"
      bindtap="onTypeTap"
      data-type="{{item}}"
    >{{item}}</view>
  </view>

  <!-- 文件列表 -->
  <skeleton wx:if="{{loading}}" count="{{4}}" />
  <view wx:else>
    <file-card wx:for="{{documents}}" wx:key="id" doc="{{item}}" />
    <view wx:if="{{documents.length === 0}}" class="empty">暂无文件</view>

    <!-- 上滑加载提示 -->
    <view wx:if="{{hasMore}}" class="load-more" bindtap="loadMore">
      ↓ 加载更多
    </view>

    <!-- 查看更多 -->
    <view class="view-more" bindtap="goCategory">
      查看更多 →
    </view>
  </view>
</view>
```

- [ ] **Step 3: index.wxss**

```css
.container { padding: 12px; padding-bottom: 30px; }

.top-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.search-box {
  flex: 1;
  display: flex;
  align-items: center;
  background: #f0f0f0;
  border-radius: 20px;
  padding: 10px 14px;
}
.search-icon { font-size: 14px; margin-right: 6px; }
.search-placeholder { font-size: 13px; color: #999; }
.fav-btn {
  width: 36px;
  height: 36px;
  background: #f5f5f5;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.update-time {
  font-size: 11px;
  color: #aaa;
  margin-bottom: 12px;
}

.category-tags {
  white-space: nowrap;
  margin-bottom: 12px;
}
.tag {
  display: inline-block;
  padding: 5px 10px;
  border-radius: 14px;
  font-size: 12px;
  background: var(--primary-light);
  color: var(--primary);
  margin-right: 6px;
}
.tag-active {
  background: var(--primary);
  color: #fff;
}

.type-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 14px;
  border-bottom: 1px solid #eee;
  padding-bottom: 8px;
}
.type-item { font-size: 12px; color: #999; }
.type-active {
  color: var(--primary);
  font-weight: 600;
  border-bottom: 2px solid var(--primary);
  padding-bottom: 8px;
  margin-bottom: -9px;
}

.load-more {
  text-align: center;
  padding: 12px;
  font-size: 12px;
  color: var(--primary);
}
.view-more {
  text-align: center;
  margin-top: 12px;
  color: var(--primary);
  border: 1px solid var(--primary);
  padding: 8px 24px;
  border-radius: 20px;
  font-size: 13px;
}
.empty { text-align: center; color: #aaa; padding: 40px; font-size: 14px; }
```

- [ ] **Step 4: index.js**

```javascript
const api = require('../../utils/api');
const storage = require('../../utils/storage');
const app = getApp();

Page({
  data: {
    categories: ['全部', '医政管理', '疾控', '妇幼健康', '基层卫生', '药政', '医管', '其他'],
    docTypes: ['全部类型', '规范性文件', '政策解读', '通知公告'],
    activeCategory: '全部',
    activeType: '全部类型',
    documents: [],
    page: 1,
    hasMore: true,
    loading: true,
    latestUpdate: ''
  },

  onShow() {
    this.setData({ page: 1, documents: [], hasMore: true });
    this.fetchDocuments();
    this.fetchLatestUpdate();
  },

  onPullDownRefresh() {
    this.setData({ page: 1, documents: [], hasMore: true });
    Promise.all([this.fetchDocuments(), this.fetchLatestUpdate()])
      .finally(() => wx.stopPullDownRefresh());
  },

  fetchDocuments() {
    this.setData({ loading: true });
    const { activeCategory, activeType, page } = this.data;
    return api.getDocuments({
      category: activeCategory,
      doc_type: activeType,
      page,
      page_size: 20
    }).then(res => {
      const docs = this.data.documents.concat(res.items);
      this.setData({
        documents: docs,
        hasMore: docs.length < res.total,
        loading: false
      });
    }).catch(() => {
      this.setData({ loading: false });
      wx.showToast({ title: '网络异常', icon: 'none' });
    });
  },

  fetchLatestUpdate() {
    return api.getLatestUpdate().then(res => {
      this.setData({ latestUpdate: res.latest_update || '' });
    });
  },

  onCategoryTap(e) {
    const cat = e.currentTarget.dataset.category;
    this.setData({ activeCategory: cat, page: 1, documents: [] });
    this.fetchDocuments();
  },

  onTypeTap(e) {
    const type = e.currentTarget.dataset.type;
    this.setData({ activeType: type, page: 1, documents: [] });
    this.fetchDocuments();
  },

  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.fetchDocuments();
  },

  goSearch() {
    wx.navigateTo({ url: '/pages/search/search' });
  },
  goFavorites() {
    wx.navigateTo({ url: '/pages/favorites/favorites' });
  },
  goCategory() {
    wx.navigateTo({
      url: `/pages/category/category?category=${this.data.activeCategory}&doc_type=${this.data.activeType}`
    });
  }
});
```

---

### Task 12: 详情页

**Files:**
- Create: `miniprogram/pages/detail/detail.json`
- Create: `miniprogram/pages/detail/detail.wxml`
- Create: `miniprogram/pages/detail/detail.wxss`
- Create: `miniprogram/pages/detail/detail.js`

- [ ] **Step 1: detail.json**

```json
{
  "navigationBarTitleText": "文件详情",
  "usingComponents": {}
}
```

- [ ] **Step 2: detail.wxml**

```xml
<view class="container" wx:if="{{!loading}}">
  <!-- 标题 + 收藏 -->
  <view class="title-row">
    <view class="title">{{doc.title}}</view>
    <view class="star {{isFav ? 'star-active' : ''}}" bindtap="toggleFav">
      {{isFav ? '★' : '☆'}}
    </view>
  </view>

  <!-- 元信息 -->
  <view class="meta" wx:if="{{doc.doc_number}}">{{doc.doc_number}}</view>
  <view class="meta">📅 {{doc.publish_date}}  🏛 {{doc.issuing_authority || '国家卫生健康委'}}</view>
  <view class="meta">📂 {{doc.category}} · {{doc.doc_type}}</view>

  <!-- 关键内容 -->
  <view class="section" wx:if="{{summary.length > 0}}">
    <view class="section-title">📌 关键内容</view>
    <view class="summary-box">
      <view wx:for="{{summary}}" wx:key="index" class="summary-item">
        <text class="summary-num">{{index + 1}}</text>
        <text>{{item}}</text>
      </view>
    </view>
  </view>

  <!-- 查看原文 -->
  <view class="btn-original" bindtap="openOriginal">📄 查看原文</view>

  <!-- 附件 -->
  <view class="section" wx:if="{{attachments.length > 0}}">
    <view class="section-title">📎 附件（{{attachments.length}}）</view>
    <view
      wx:for="{{attachments}}"
      wx:key="name"
      class="attach-item"
      bindtap="openAttachment"
      data-url="{{item.url}}"
    >📄 {{item.name}}</view>
  </view>
</view>

<!-- 加载态 -->
<view wx:else class="loading">加载中...</view>
```

- [ ] **Step 3: detail.wxss**

```css
.container { padding: 16px; }
.title-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}
.title {
  flex: 1;
  font-size: 18px;
  font-weight: 700;
  color: #222;
  line-height: 1.5;
}
.star {
  font-size: 22px;
  color: #ccc;
  padding: 4px;
}
.star-active { color: var(--primary); }

.meta { font-size: 13px; color: #888; margin-bottom: 4px; }

.section { margin-top: 20px; }
.section-title {
  font-size: 14px;
  font-weight: 700;
  color: #333;
  margin-bottom: 10px;
}

.summary-box {
  background: #f8f9fa;
  border-radius: 8px;
  padding: 14px;
}
.summary-item {
  display: flex;
  gap: 8px;
  font-size: 13px;
  color: #444;
  margin-bottom: 10px;
  line-height: 1.6;
}
.summary-item:last-child { margin-bottom: 0; }
.summary-num { font-weight: 700; color: var(--primary); flex-shrink: 0; }

.btn-original {
  display: block;
  background: var(--primary);
  color: #fff;
  text-align: center;
  padding: 12px;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  margin-top: 20px;
}

.attach-item {
  font-size: 13px;
  color: var(--primary);
  padding: 10px 12px;
  background: var(--primary-light);
  border-radius: 6px;
  margin-bottom: 6px;
}
.loading { text-align: center; color: #aaa; padding: 60px 0; }
```

- [ ] **Step 4: detail.js**

```javascript
const api = require('../../utils/api');
const storage = require('../../utils/storage');

Page({
  data: {
    doc: {},
    summary: [],
    attachments: [],
    isFav: false,
    loading: true
  },

  onLoad(options) {
    const id = parseInt(options.id);
    api.getDocumentDetail(id).then(doc => {
      let summary = [];
      let attachments = [];
      try { summary = JSON.parse(doc.summary || '[]'); } catch(e) {}
      try { attachments = JSON.parse(doc.attachments || '[]'); } catch(e) {}

      this.setData({
        doc,
        summary,
        attachments,
        isFav: storage.isFavorited(doc.id),
        loading: false
      });
    }).catch(() => {
      this.setData({ loading: false });
      wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  toggleFav() {
    const added = storage.toggleFavorite(this.data.doc);
    this.setData({ isFav: added });
    wx.showToast({
      title: added ? '已加入收藏' : '已取消收藏',
      icon: 'none',
      duration: 1500
    });
  },

  openOriginal() {
    if (this.data.doc.original_url) {
      wx.setClipboardData({
        data: this.data.doc.original_url,
        success: () => wx.showToast({ title: '链接已复制', icon: 'none' })
      });
    }
  },

  openAttachment(e) {
    const url = e.currentTarget.dataset.url;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '链接已复制', icon: 'none' })
    });
  }
});
```

---

### Task 13: 搜索页

**Files:**
- Create: `miniprogram/pages/search/search.json`
- Create: `miniprogram/pages/search/search.wxml`
- Create: `miniprogram/pages/search/search.wxss`
- Create: `miniprogram/pages/search/search.js`

- [ ] **Step 1: search.json**

```json
{
  "usingComponents": {
    "file-card": "/components/file-card/file-card"
  }
}
```

- [ ] **Step 2: search.wxml**

```xml
<view class="container">
  <view class="search-bar">
    <view class="back" bindtap="goBack">←</view>
    <input
      class="search-input"
      placeholder="输入关键词搜索..."
      focus="{{true}}"
      value="{{keyword}}"
      bindinput="onInput"
      bindconfirm="onSearch"
    />
  </view>

  <view class="result-count" wx:if="{{searched}}">找到 {{total}} 条结果</view>

  <file-card wx:for="{{results}}" wx:key="id" doc="{{item}}" />

  <view wx:if="{{searched && results.length === 0}}" class="empty">📭 暂无结果，换个关键词试试</view>

  <view wx:if="{{hasMore}}" class="load-more" bindtap="loadMore">↓ 加载更多</view>
</view>
```

- [ ] **Step 3: search.wxss** (与首页类似的关键样式)

```css
.container { padding: 12px; }
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.back { font-size: 16px; color: #999; padding: 4px; }
.search-input {
  flex: 1;
  background: #f0f0f0;
  border-radius: 20px;
  padding: 10px 14px;
  font-size: 14px;
}
.result-count { font-size: 12px; color: #999; margin-bottom: 10px; }
.empty { text-align: center; color: #aaa; padding: 40px; font-size: 14px; }
.load-more { text-align: center; padding: 12px; font-size: 12px; color: var(--primary); }
```

- [ ] **Step 4: search.js**

```javascript
const api = require('../../utils/api');

Page({
  data: {
    keyword: '',
    results: [],
    total: 0,
    page: 1,
    hasMore: false,
    searched: false
  },

  onInput(e) { this.setData({ keyword: e.detail.value }); },

  onSearch() {
    this.setData({ page: 1, results: [], searched: true });
    this.doSearch();
  },

  doSearch() {
    const { keyword, page } = this.data;
    if (!keyword.trim()) return;
    api.searchDocuments({ q: keyword, page, page_size: 20 }).then(res => {
      const list = this.data.results.concat(res.items);
      this.setData({
        results: list,
        total: res.total,
        hasMore: list.length < res.total
      });
    }).catch(() => {
      wx.showToast({ title: '搜索失败', icon: 'none' });
    });
  },

  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.doSearch();
  },

  goBack() { wx.navigateBack(); }
});
```

---

### Task 14: 分类列表页

**Files:**
- Create: `miniprogram/pages/category/category.json`
- Create: `miniprogram/pages/category/category.wxml`
- Create: `miniprogram/pages/category/category.wxss`
- Create: `miniprogram/pages/category/category.js`

- [ ] **Step 1: category.json**

```json
{
  "usingComponents": {
    "file-card": "/components/file-card/file-card"
  }
}
```

- [ ] **Step 2: category.wxml**

```xml
<view class="container">
  <view class="header">
    <view class="back" bindtap="goBack">←</view>
    <view class="header-title">📂 {{category}} · {{docType}}</view>
  </view>

  <view class="total">共 {{total}} 条</view>

  <file-card wx:for="{{documents}}" wx:key="id" doc="{{item}}" />

  <view wx:if="{{hasMore}}" class="load-more" bindtap="loadMore">↓ 加载更多</view>
</view>
```

- [ ] **Step 3: category.wxss**

```css
.container { padding: 12px; }
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.back { font-size: 16px; color: #999; padding: 4px; }
.header-title { font-size: 15px; font-weight: 600; color: #333; }
.total { font-size: 12px; color: #aaa; margin-bottom: 10px; }
.load-more { text-align: center; padding: 12px; font-size: 12px; color: var(--primary); }
```

- [ ] **Step 4: category.js**

```javascript
const api = require('../../utils/api');

Page({
  data: {
    category: '',
    docType: '',
    documents: [],
    total: 0,
    page: 1,
    hasMore: false
  },

  onLoad(options) {
    const category = options.category || '全部';
    const docType = options.doc_type || '全部类型';
    this.setData({ category, docType });
    this.fetchList();
  },

  fetchList() {
    const { category, docType, page } = this.data;
    api.getDocuments({ category, doc_type: docType, page, page_size: 20 }).then(res => {
      const list = this.data.documents.concat(res.items);
      this.setData({
        documents: list,
        total: res.total,
        hasMore: list.length < res.total
      });
    });
  },

  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.fetchList();
  },

  goBack() { wx.navigateBack(); }
});
```

---

### Task 15: 收藏页

**Files:**
- Create: `miniprogram/pages/favorites/favorites.json`
- Create: `miniprogram/pages/favorites/favorites.wxml`
- Create: `miniprogram/pages/favorites/favorites.wxss`
- Create: `miniprogram/pages/favorites/favorites.js`

- [ ] **Step 1: favorites.json**

```json
{
  "usingComponents": {
    "file-card": "/components/file-card/file-card"
  }
}
```

- [ ] **Step 2: favorites.wxml**

```xml
<view class="container">
  <view class="header">
    <view class="back" bindtap="goBack">←</view>
    <view class="header-title">⭐ 我的收藏</view>
  </view>

  <view class="total" wx:if="{{favorites.length > 0}}">共 {{favorites.length}} 条</view>

  <file-card wx:for="{{favorites}}" wx:key="id" doc="{{item}}" />

  <view wx:if="{{favorites.length === 0}}" class="empty">📭 暂无收藏</view>
</view>
```

- [ ] **Step 3: favorites.wxss**

```css
.container { padding: 12px; }
.header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.back { font-size: 16px; color: #999; padding: 4px; }
.header-title { font-size: 15px; font-weight: 600; color: #333; }
.total { font-size: 12px; color: #aaa; margin-bottom: 10px; }
.empty { text-align: center; color: #aaa; padding: 60px 0; font-size: 14px; }
```

- [ ] **Step 4: favorites.js**

```javascript
const storage = require('../../utils/storage');

Page({
  data: { favorites: [] },

  onShow() {
    this.setData({ favorites: storage.getFavorites() });
  },

  goBack() { wx.navigateBack(); }
});
```

---

### Task 16: 首页订阅引导弹窗

**Files:**
- Modify: `miniprogram/pages/index/index.js`（添加弹窗逻辑）

- [ ] **Step 1: 在 index.js 中添加订阅引导**

在 `onShow()` 方法开头添加：
```javascript
// 首次打开引导订阅
const hasShownGuide = wx.getStorageSync('subscription_guide_shown');
if (!hasShownGuide) {
  wx.showModal({
    title: '开启新文件提醒',
    content: '每日上午9:00推送昨日新增政策文件，不再错过重要通知',
    cancelText: '暂不需要',
    confirmText: '去开启',
    success: (res) => {
      if (res.confirm) {
        wx.requestSubscribeMessage({
          tmplIds: ['YOUR_TEMPLATE_ID'],
          success: () => {},
          fail: () => wx.showToast({ title: '订阅失败', icon: 'none' })
        });
      }
      wx.setStorageSync('subscription_guide_shown', true);
    }
  });
}
```

---

## Phase 3: 集成验证

### Task 17: 端到端验证

- [ ] **Step 1: 启动后端并验证所有 API**

```bash
cd /Users/hulei/Documents/test/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 2
# 测试所有接口
curl -s http://localhost:8000/api/v1/documents?page=1&page_size=5 | python3 -m json.tool
curl -s http://localhost:8000/api/v1/documents/latest-update | python3 -m json.tool
curl -s "http://localhost:8000/api/v1/documents/search?q=通知&page=1" | python3 -m json.tool
```

- [ ] **Step 2: 微信开发者工具打开 miniprogram 目录**

确认：
- 首页正常加载（骨架屏 → 文件列表）
- 点击文件卡片 → 详情页正常展示
- 详情页收藏/取消收藏 → Toast 反馈
- 搜索页输入关键词 → 结果列表
- 分类标签切换 → 列表联动
- 收藏页查看 → 已收藏文件

- [ ] **Step 3: 验证错误态和空态**

在后端关闭时测试：
- 首页显示"网络异常"
- 搜索无结果时显示"暂无结果"
- 无收藏时显示"暂无收藏"

---

## 后续扩展（不在本次计划）

- 后端部署（云服务器 + Docker + 域名 + HTTPS）
- 微信小程序审核上架
- 历史数据批量导入
- 多条件组合筛选
- NHC 改版后爬虫适配策略
