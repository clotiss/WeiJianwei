"""
===============================================================================
数据库连接层 — SQLAlchemy ORM 配置
===============================================================================

本文件负责：
1. 创建数据库引擎（engine）— 连接 SQLite 数据库
2. 创建会话工厂（SessionLocal）— 每次数据库操作获取一个会话
3. 声明 ORM 基类（Base）— 所有数据表模型继承此类

使用方式（在 API 路由中）：
    db = SessionLocal()
    try:
        result = db.query(Model).filter(...).all()
    finally:
        db.close()  # 务必关闭会话，避免连接泄漏
"""

from sqlalchemy import create_engine                               # 数据库引擎
from sqlalchemy.orm import sessionmaker, declarative_base          # 会话工厂 & ORM 基类

from config import DATABASE_URL

# =============================================================================
# 1. 创建数据库引擎
#    connect_args={"check_same_thread": False} 是 SQLite 必需的参数，
#    因为 FastAPI 是异步框架，可能从不同线程访问 SQLite，
#    SQLite 默认只允许同一线程访问，加上此参数解除限制
# =============================================================================
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# =============================================================================
# 2. 创建会话工厂
#    autocommit=False: 不自动提交事务，需要手动 commit()
#    autoflush=False: 不自动刷新，避免意外的数据库写入
#    bind=engine: 绑定到上面创建的 SQLite 引擎
# =============================================================================
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# =============================================================================
# 3. 声明 ORM 基类
#    所有数据表模型（Document, Favorite）都需要继承这个 Base
#    调用 Base.metadata.create_all() 即可自动创建所有继承自 Base 的表
# =============================================================================
Base = declarative_base()
