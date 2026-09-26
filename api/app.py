"""FastAPI application entrypoint.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from api.http import health, tasks
from api.ws import stream
from api.ws.session_registry import SessionRegistry
from composition.bootstrap import build_host_components
from config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    components = build_host_components(settings)
    components.worker.start()
    ingest_deps = tasks.IngestDeps(
        store=components.store,
        source_tokens=tasks.parse_source_tokens(settings.ingest_source_tokens),
    )
    app.state.ingest_deps = ingest_deps

    app.state.host_components = components
    app.state.stream_deps = stream.StreamDeps(
        worker=components.worker,
        session_registry=SessionRegistry(),
        audio_sample_rate_hz=settings.audio_sample_rate_hz,
        session_timeout_seconds=float(settings.session_timeout_seconds),
    )
    try:
        yield
    finally:
        components.worker.stop(timeout=settings.session_timeout_seconds)
        components.runner.close()


app = FastAPI(title="SYNCRO Host", lifespan=lifespan)

app.include_router(health.router)
app.include_router(tasks.router)
app.include_router(stream.router)
