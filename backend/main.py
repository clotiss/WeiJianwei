"""
===============================================================================
NHC Policy API — FastAPI 应用入口
国家卫健委政策文件查询系统 · 后端主程序
===============================================================================

本文件是整个后端服务的启动入口，负责：
1. 创建 FastAPI 应用实例
2. 配置 CORS 跨域中间件（允许小程序前端访问）
3. 自动创建数据库表结构
4. 注册文档查询和收藏功能的 API 路由
5. 在应用启动时启动定时抓取调度器
"""

# ---------- FastAPI 核心 ----------
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------- 数据库相关 ----------
from database import engine, Base           # engine: 数据库引擎；Base: ORM 基类
from models import Document, Favorite       # 导入模型以触发表创建

# ---------- API 路由 ----------
from api.documents import router as documents_router

# =============================================================================
# 1. 自动建表 — 根据 models.py 中定义的表结构，在 SQLite 中创建对应的表
#    如果表已存在则跳过，不会重复创建
# =============================================================================
Base.metadata.create_all(bind=engine)

# =============================================================================
# 2. 创建 FastAPI 应用实例
#    title: Swagger 文档页面的标题
#    version: API 版本号
# =============================================================================
app = FastAPI(title="NHC Policy API", version="0.1.0")

# =============================================================================
# 3. 配置 CORS 跨域中间件
#    微信小程序通过 wx.request 发起的请求属于跨域请求，
#    必须配置 CORS 允许所有来源、方法和请求头
# =============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 允许所有来源（生产环境建议限制具体域名）
    allow_methods=["*"],       # 允许所有 HTTP 方法（GET/POST/DELETE 等）
    allow_headers=["*"],       # 允许所有请求头
)

# =============================================================================
# 4. 注册路由
#    - documents_router: /api/v1/documents/*  → 文件查询、搜索、分类
#    - favorites_router: /api/v1/favorites/*  → 收藏管理
# =============================================================================
app.include_router(documents_router)

# 收藏路由用 try-except 包裹，即使 favorites.py 不存在也不会导致整个应用崩溃
try:
    from api.favorites import router as favorites_router
    app.include_router(favorites_router)
except ImportError:
    pass

# Agent 智能检索路由 — 自然语言搜索政策文件
try:
    from api.agent import router as agent_router
    app.include_router(agent_router)
except ImportError:
    pass

# ---------- 定时任务调度器 ----------
from services.scheduler import start_scheduler


# =============================================================================
# 5. 应用启动事件 — FastAPI 启动后自动执行
#    启动后台定时调度器，按配置的间隔自动抓取 NHC 官网的政策文件
# =============================================================================
@app.on_event("startup")
def on_startup():
    """应用启动时自动调用：启动后台定时抓取调度器。"""
    start_scheduler()
