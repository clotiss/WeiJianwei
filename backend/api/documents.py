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
