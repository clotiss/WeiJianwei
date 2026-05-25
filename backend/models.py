from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Index
from database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    doc_number = Column(String(100))
    issuing_authority = Column(String(200), default="国家卫生健康委")
    publish_date = Column(String(20), nullable=False)
    category = Column(String(100), nullable=False)
    doc_type = Column(String(100), nullable=False)
    original_url = Column(String(500), nullable=False)
    summary = Column(Text)
    attachments = Column(Text)  # JSON string
    created_at = Column(String(20), default=lambda: datetime.now().isoformat())

    __table_args__ = (
        Index("idx_publish_date", "publish_date"),
        Index("idx_category", "category"),
        Index("idx_doc_type", "doc_type"),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_id = Column(Integer, nullable=False)
    created_at = Column(String(20), default=lambda: datetime.now().isoformat())
