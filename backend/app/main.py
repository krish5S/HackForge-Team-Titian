from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.decisions import router as decisions_router
from app.api.health import router as health_router
from app.api.receipts import router as receipts_router
from app.db.database import engine
from app.db.models import Base
from app.errors import register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(
    title="Receipt Graveyard API",
    description="Expense review and policy verification API.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(health_router, prefix="/api")
app.include_router(decisions_router, prefix="/api")
app.include_router(receipts_router, prefix="/api")