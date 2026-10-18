from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import ALLOWED_ORIGINS, require_reviewer
from app.api.employee import router as employee_router
from app.upload_limit import UploadLimitMiddleware
from app.api.auth import router as auth_router
from app.api.decisions import router as decisions_router
from app.api.health import router as health_router
from app.api.receipts import router as receipts_router
from app.db.database import engine
from app.db.models import Base
from app.db.upload_migration import migrate_uploads
from app.errors import register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_uploads(engine)

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

app.add_middleware(UploadLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(decisions_router, prefix="/api", dependencies=[Depends(require_reviewer)])
app.include_router(receipts_router, prefix="/api", dependencies=[Depends(require_reviewer)])
app.include_router(employee_router, prefix="/api")
