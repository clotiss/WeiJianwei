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
