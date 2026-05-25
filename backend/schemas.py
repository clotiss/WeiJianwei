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
