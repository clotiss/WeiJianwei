"""
===============================================================================
数据模型定义 — SQLAlchemy ORM 模型
===============================================================================

本文件定义了两个数据库表：
1. documents  — 政策文件表，存储抓取的 NHC 规范性文件及政策解读
2. favorites  — 收藏表，记录用户收藏的文件 ID

字段说明与索引策略：
- publish_date、category、doc_type 建立索引以加速查询和筛选
- attachments 以 JSON 字符串存储，可灵活存放文件附件列表
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Index
from database import Base


class Document(Base):
    """
    政策文件表 — 存储从 NHC 卫健委官网抓取的政策文件全部信息。

    字段说明：
    - id: 自增主键
    - title: 文件标题（最长 500 字符）
    - doc_number: 文件发文字号（如"国卫办发〔2024〕15号"）
    - issuing_authority: 发文机关，默认为"国家卫生健康委"
    - publish_date: 发布日期（字符串格式，如"2024-06-01"）
    - category: 文件分类（由 AI 自动归类到 8 大类之一）
    - doc_type: 文件类型（"规范性文件"或"政策解读"）
    - original_url: 原文链接（用于跳转查看原始页面）
    - content: 文件正文内容
    - summary: AI 生成的关键要点摘要（JSON 数组字符串）
    - attachments: 附件列表（JSON 字符串：[{"name": "...", "url": "..."}]）
    - created_at: 记录入库时间
    """
    __tablename__ = "documents"

    # ---------- 主键 ----------
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ---------- 基本信息 ----------
    title = Column(String(500), nullable=False)                    # 文件标题（必填）
    doc_number = Column(String(100))                               # 发文字号（可选）
    issuing_authority = Column(String(200), default="国家卫生健康委")  # 发文机关
    publish_date = Column(String(20), nullable=False)              # 发布日期（必填）

    # ---------- 分类信息 ----------
    category = Column(String(100), nullable=False)                 # AI 分类标签
    doc_type = Column(String(100), nullable=False)                 # 文件类型

    # ---------- 内容与链接 ----------
    original_url = Column(String(500), nullable=False)             # 源文链接
    content = Column(Text)                                          # 正文内容（可能很长，用 Text 类型）
    summary = Column(Text)                                          # AI 要点摘要（JSON 数组字符串）
    attachments = Column(Text)                                      # 附件列表（JSON 字符串）

    # ---------- 元数据 ----------
    created_at = Column(String(20), default=lambda: datetime.now().isoformat())

    # ---------- 数据库索引 ----------
    # 在 publish_date、category、doc_type 上建索引
    # 列表页按日期排序、按分类/类型筛选时，索引可以大幅提升查询速度
    __table_args__ = (
        Index("idx_publish_date", "publish_date"),
        Index("idx_category", "category"),
        Index("idx_doc_type", "doc_type"),
    )


class Favorite(Base):
    """
    收藏表 — 记录用户收藏的文件。

    简化设计说明：
    本系统只有"收藏/取消收藏"两种状态，没有用户系统，
    所以只存 doc_id 即可。多用户场景可扩展 openid 字段。
    """
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)     # 自增主键
    doc_id = Column(Integer, nullable=False)                        # 被收藏的文件 ID
    created_at = Column(String(20), default=lambda: datetime.now().isoformat())
