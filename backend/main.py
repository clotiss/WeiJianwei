from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from models import Document, Favorite
from api.documents import router as documents_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="NHC Policy API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)

try:
    from api.favorites import router as favorites_router

    app.include_router(favorites_router)
except ImportError:
    pass

from services.scheduler import start_scheduler


@app.on_event("startup")
def on_startup():
    start_scheduler()
