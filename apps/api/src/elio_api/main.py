from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from elio_api import __version__
from elio_api.api.routes import actors, auth, evidence, exceptions, health, sync, work_items
from elio_api.api.routes.work_items import templates_router
from elio_api.config import get_settings
from elio_api.logging_config import configure_logging
from elio_api.middleware import RequestContextMiddleware
from elio_api.schemas import ErrorResponse

settings = get_settings()
configure_logging(level=settings.log_level, json_logs=settings.log_json)
logger = structlog.get_logger("elio.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("elio.api.starting", environment=settings.environment, version=__version__)
    yield
    logger.info("elio.api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(actors.router, prefix="/api/v1")
    app.include_router(templates_router, prefix="/api/v1")
    app.include_router(work_items.router, prefix="/api/v1")
    app.include_router(exceptions.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")
    app.include_router(evidence.router, prefix="/api/v1")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", "unknown")
        logger.error(
            "elio.api.unhandled_exception",
            correlation_id=correlation_id,
            path=request.url.path,
            exc_info=exc,
        )
        body = ErrorResponse(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            correlation_id=correlation_id,
            retryable=False,
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    return app


app = create_app()
