"""
===============================================================================
文件查询 API — 政策文件的检索、搜索、详情接口
===============================================================================

本文件是系统最核心的 API 模块，提供以下接口：

GET  /api/v1/documents/categories      — 获取所有分类列表（用于首页标签筛选）
GET  /api/v1/documents                 — 分页获取文件列表（支持按分类/类型筛选）
GET  /api/v1/documents/search          — 按关键词搜索文件（标题+发文机关）
GET  /api/v1/documents/latest-update   — 获取最近入库文件的日期
GET  /api/v1/documents/{doc_id}        — 获取单篇文件详情

所有接口都遵循：创建 DB 会话 → 查询 → 返回 → finally 中关闭会话的模式，
确保数据库连接不泄漏。
"""

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import desc, or_, func
from database import SessionLocal
from models import Document
from schemas import DocumentItem, DocumentListResponse, SearchResponse, LatestUpdateResponse

# =============================================================================
# 创建路由实例
# prefix: 所有接口的 URL 前缀
# tags: Swagger 文档中的分组标签
# =============================================================================
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.get("/categories")
def list_categories():
    """
    获取所有文件分类列表。

    从 documents 表中查询不重复的 category 字段值，按字母排序后返回。
    小程序首页的标签筛选区域使用此接口动态生成分类按钮。

    返回格式：{"categories": ["妇幼健康与人口发展", "疾病预防控制与公共卫生", ...]}
    """
    db = SessionLocal()
    try:
        # 查询所有不重复的非空分类
        rows = db.query(Document.category).filter(Document.category != "").distinct().all()
        # 提取为纯字符串列表并排序
        categories = sorted([r[0] for r in rows if r[0]])
        return {"categories": categories}
    finally:
        db.close()  # 无论成功或异常，都要关闭数据库会话


@router.get("", response_model=DocumentListResponse)
def list_documents(
    category: str = Query(default=""),           # 分类筛选（空字符串表示不筛选）
    doc_type: str = Query(default=""),           # 文件类型筛选（空字符串表示不筛选）
    page: int = Query(default=1, ge=1),           # 页码，从 1 开始，最小值为 1
    page_size: int = Query(default=20, ge=1, le=100),  # 每页条数，1-100
):
    """
    分页获取文件列表。

    支持按分类（category）和文件类型（doc_type）组合筛选。
    结果按发布日期降序排列（最新文件在最前面）。

    前端"上滑加载更多"功能：每次 page+1 追加数据到列表末尾。
    """
    db = SessionLocal()
    try:
        q = db.query(Document)

        # ---- 条件筛选 ----
        # "全部"代表不筛选，空字符串也代表不筛选
        if category and category != "全部":
            q = q.filter(Document.category == category)
        if doc_type and doc_type != "全部类型":
            q = q.filter(Document.doc_type == doc_type)

        # ---- 分页查询 ----
        total = q.count()                                              # 符合条件的总记录数
        items = (
            q.order_by(desc(Document.publish_date))                   # 按发布日期降序
            .offset((page - 1) * page_size)                           # 跳过前 (page-1) 页
            .limit(page_size)                                          # 只取当前页
            .all()
        )

        # ---- 构造响应 ----
        # model_validate 将 SQLAlchemy ORM 对象转为 Pydantic Schema 对象
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
    q: str = Query(default="", alias="q"),        # 搜索关键词（alias="q" 允许 URL 中用 ?q=xxx）
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """
    按关键词搜索文件。

    搜索范围：文件标题（title）+ 发文机关（issuing_authority）
    使用 SQL LIKE 模糊匹配（contains 方法），支持中文关键词。
    """
    db = SessionLocal()
    try:
        # or_ 表示"或"条件：标题包含关键词 OR 发文机关包含关键词
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
    """
    获取最近入库文件的日期。

    按 created_at（入库时间）排序取最新一条，
    返回其 created_at 字段。
    小程序首页顶部显示"最新发布文件：2024-06-01"。
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).order_by(desc(Document.created_at)).first()
        return LatestUpdateResponse(latest_update=doc.created_at if doc else None)
    finally:
        db.close()


@router.get("/{doc_id}", response_model=DocumentItem)
def get_document(doc_id: int):
    """
    获取单篇文件详情。

    根据文件 ID 查询完整信息（包括正文内容），
    如果 ID 不存在则返回 404 错误。

    小程序详情页调用此接口展示文件的完整信息。
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            # 文件不存在时抛出 404，FastAPI 自动返回 {"detail": "Document not found"}
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentItem.model_validate(doc)
    finally:
        db.close()
