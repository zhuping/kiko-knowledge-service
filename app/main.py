from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.http import install_http, ok
from app.api.v1.router import router
from app.core.config import settings
from app.core.database import check_database, engine
from app.models import Base


@asynccontextmanager
async def lifespan(_app):
    if settings.environment == "development":
        Base.metadata.create_all(engine)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Kiko Curriculum Knowledge Service",
        version="0.1.0",
        description="版本化教材知识包、可追溯题目判断与反馈审核 API。",
        lifespan=lifespan,
    )
    if settings.environment == "development":
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    install_http(application)
    application.include_router(router)

    @application.get("/health/live", tags=["health"])
    def live():
        return ok({"status": "ok"})

    @application.get("/health/ready", tags=["health"])
    def ready():
        check_database()
        return ok({"status": "ready", "database": "ok"})

    return application


app = create_app()
