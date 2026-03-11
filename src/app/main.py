from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings
from app.core.container import AppContainer, build_container


def create_app(
    *,
    settings: Optional[Settings] = None,
    container: Optional[AppContainer] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active_container = container or build_container(settings)
        app.state.container = active_container
        await active_container.start()
        try:
            yield
        finally:
            await active_container.stop()

    active_settings = settings or (container.settings if container else Settings())
    app = FastAPI(
        title=active_settings.app_name,
        lifespan=lifespan,
    )
    app.include_router(router, prefix=active_settings.api_prefix)
    return app


app = create_app()


def run() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
