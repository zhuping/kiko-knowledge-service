from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.api.admin import router as admin_router
from app.api.admin_jobs import router as admin_jobs_router
from app.api.admin_release import router as admin_release_router
from app.api.open import router as open_router
from app.core.config import Settings
from app.core.db import create_database_engine
from app.core.errors import BusinessError
from app.core.response import failure
from app.models import Base
from app.modules.catalog.service import seed_textbook_editions


def create_app(database_url: str | None = None, create_schema: bool = False) -> FastAPI:
    settings = Settings()
    if database_url:
        settings.database_url = database_url
    engine = create_database_engine(settings.database_url)
    if create_schema:
        Base.metadata.create_all(engine)
    app = FastAPI(title="Kiko Knowledge Service", version="1.0.0")
    app.state.settings = settings
    app.state.engine = engine
    # ponytail: process-local sessions; use a shared store for multiple workers
    app.state.admin_sessions = {}
    app.state.session_factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    if create_schema:
        with app.state.session_factory() as session:
            seed_textbook_editions(session)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get(
            "X-Request-ID", f"req_{uuid4().hex}"
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(BusinessError)
    async def business_error_handler(request: Request, exc: BusinessError):
        return JSONResponse(
            status_code=exc.status_code,
            content=failure(
                exc.code, exc.message, request.state.request_id, exc.details
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=failure(
                "PARAM_INVALID", "请求参数无效", request.state.request_id, exc.errors()
            ),
        )

    @app.get("/healthz", tags=["system"])
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    def readyz():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - depends on external DB
            return JSONResponse(
                status_code=503, content={"status": "not_ready", "error": str(exc)}
            )
        return {"status": "ready"}

    app.include_router(admin_router)
    app.include_router(admin_jobs_router)
    app.include_router(admin_release_router)
    app.include_router(open_router)
    return app


app = create_app()
