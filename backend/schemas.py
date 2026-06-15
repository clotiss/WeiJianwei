"""
===============================================================================
Pydantic 数据模式（Schema）— 请求/响应的数据结构定义
===============================================================================

Pydantic 是 FastAPI 的数据验证库。本文件定义的类用于：
1. 定义 API 接口的请求体和响应体结构（自动生成 Swagger 文档）
2. 对输入数据进行类型校验和自动转换
3. 控制哪些字段暴露给前端（ORM 对象 → JSON）

与 models.py 的区别：
- models.py：数据库层面的表结构定义（SQLAlchemy ORM）
- schemas.py：API 层面的数据结构定义（Pydantic）— 两层解耦便于维护
"""

from pydantic import BaseModel
from typing import Optional


class DocumentItem(BaseModel):
    """
    单条文件记录的返回格式。

    Optional 字段在值为空时会返回默认值（空字符串或"[]"），
    而非 null，这样小程序前端不需要做额外的空值判断。
    """
    id: int
    title: str
    doc_number: Optional[str] = ""          # 发文字号，可能为空
    issuing_authority: Optional[str] = ""   # 发文机关
    publish_date: str                        # 发布日期
    category: str                            # AI 分类标签
    doc_type: str                            # 文件类型
    original_url: Optional[str] = ""         # 原文链接
    content: Optional[str] = ""              # 正文内容（列表页不需要，详情页才用到）
    summary: Optional[str] = ""              # AI 摘要（JSON 字符串）
    attachments: Optional[str] = "[]"        # 附件列表（JSON 字符串，默认空数组）

    class Config:
        # from_attributes=True 允许从 SQLAlchemy ORM 对象直接创建 Pydantic 模型
        # （Pydantic v2 中替代了 v1 的 orm_mode=True）
        from_attributes = True


class DocumentListResponse(BaseModel):
    """
    文件列表接口的返回格式（带分页信息）。

    前端通过 total、page、page_size 判断是否还有更多数据，
    实现"上滑加载更多"功能。
    """
    items: list[DocumentItem]    # 当前页的文件列表
    total: int                    # 符合条件的总记录数
    page: int                     # 当前页码
    page_size: int                # 每页条数


class SearchResponse(DocumentListResponse):
    """
    搜索接口的返回格式 — 继承列表格式，额外返回搜索关键词。
    """
    query: str                    # 用户输入的搜索关键词


class LatestUpdateResponse(BaseModel):
    """
    最新更新时间接口的返回格式。
    首页顶部展示"最新文件发布于 YYYY-MM-DD"，让用户感知数据新鲜度。
    """
    latest_update: Optional[str]  # 最近入库文件的日期


class FavoriteCreate(BaseModel):
    """
    添加收藏的请求体格式。
    只需传 doc_id，后端自动记录收藏时间。
    """
    doc_id: int


# =============================================================================
# Agent 智能检索 — 请求/响应模型
# =============================================================================

class AgentRequest(BaseModel):
    """Agent 检索请求体 — 用户输入的自然语言查询。"""
    query: str
    session_id: Optional[str] = None  # 可选会话 ID，传入则启用多轮对话记忆


class AgentResponse(BaseModel):
    """
    Agent 检索响应体。

    与普通搜索不同，Agent 不仅返回文件列表，还包含：
    - answer: LLM 生成的自然语言回答，引用具体文件名
    - thinking_steps: 执行过程中每一步的说明（方便调试和用户理解）
    """
    answer: str
    documents: list[DocumentItem]
    thinking_steps: list[str]
