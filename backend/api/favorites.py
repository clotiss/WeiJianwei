"""
===============================================================================
收藏管理 API — 用户的文件收藏功能
===============================================================================

提供以下接口：

GET    /api/v1/favorites         — 获取收藏列表
POST   /api/v1/favorites         — 添加收藏
DELETE /api/v1/favorites/{doc_id} — 取消收藏

注意：当前版本为简化设计，收藏数据存储在服务端数据库而非本地。
如需切换为本地存储方案，可使用小程序端的 storage.js 工具函数。
"""

from fastapi import APIRouter, HTTPException
from database import SessionLocal
from models import Favorite, Document
from schemas import FavoriteCreate, DocumentItem

router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])


@router.get("")
def list_favorites():
    """
    获取收藏列表。

    按收藏时间倒序排列（最近收藏的在前），
    关联查询 documents 表获取文件完整信息。

    返回格式：{"items": [...], "total": N}
    """
    db = SessionLocal()
    try:
        # 按收藏时间倒序查询所有收藏记录
        favs = db.query(Favorite).order_by(Favorite.created_at.desc()).all()
        items = []
        for f in favs:
            # 根据 doc_id 关联查询文件信息
            doc = db.query(Document).filter(Document.id == f.doc_id).first()
            if doc:
                items.append(DocumentItem.model_validate(doc))
        return {"items": items, "total": len(items)}
    finally:
        db.close()


@router.post("")
def add_favorite(body: FavoriteCreate):
    """
    添加收藏。

    请求体格式：{"doc_id": 123}
    逻辑：
    1. 检查文件是否存在（不存在返回 404）
    2. 检查是否已收藏（已收藏则直接返回成功，不重复添加）
    3. 创建收藏记录
    """
    db = SessionLocal()
    try:
        # 校验文件是否存在
        doc = db.query(Document).filter(Document.id == body.doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        # 检查是否已收藏（防止重复）
        existing = (
            db.query(Favorite).filter(Favorite.doc_id == body.doc_id).first()
        )
        if existing:
            return {"status": "already_favorited"}

        # 创建收藏记录
        fav = Favorite(doc_id=body.doc_id)
        db.add(fav)       # 加入会话
        db.commit()       # 提交到数据库
        return {"status": "ok"}
    finally:
        db.close()


@router.delete("/{doc_id}")
def remove_favorite(doc_id: int):
    """
    取消收藏。

    根据文件 ID 删除对应的收藏记录。
    如果该文件未被收藏过，返回 404。
    """
    db = SessionLocal()
    try:
        fav = db.query(Favorite).filter(Favorite.doc_id == doc_id).first()
        if not fav:
            raise HTTPException(status_code=404, detail="Favorite not found")
        db.delete(fav)    # 标记为删除
        db.commit()       # 提交删除操作
        return {"status": "ok"}
    finally:
        db.close()
