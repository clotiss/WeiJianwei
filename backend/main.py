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

from contextlib import asynccontextmanager
import asyncio

# ---------- FastAPI 核心 ----------
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------- 数据库相关 ----------
from database import engine, Base
from models import Document, Favorite

# ---------- API 路由 ----------
from api.documents import router as documents_router

# =============================================================================
# 1. 自动建表 — 根据 models.py 中定义的表结构，在 SQLite 中创建对应的表
# =============================================================================
Base.metadata.create_all(bind=engine)

# ---------- 定时任务调度器 ----------
from services.scheduler import start_scheduler


# =============================================================================
# 2. 应用生命周期
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化调度器，关闭时清理资源。"""
    start_scheduler()
    print("[main] ✅ Scheduler started")
    yield
    print("[main] Shutting down...")


# =============================================================================
# 3. 创建 FastAPI 应用实例
# =============================================================================
app = FastAPI(title="NHC Policy API", version="0.1.0", lifespan=lifespan)

# =============================================================================
# 4. 配置 CORS 跨域中间件
# =============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# 5. 注册路由
# =============================================================================
app.include_router(documents_router)

try:
    from api.favorites import router as favorites_router
    app.include_router(favorites_router)
except ImportError:
    pass

try:
    from api.agent import router as agent_router
    app.include_router(agent_router)
except ImportError:
    pass
