import asyncio
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.core.cache import EventCache
from app.core.broadcaster import Broadcaster
from app.api import ingest, stream, auth


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.cache = EventCache(maxlen=settings.cache_max_events)
    broadcaster = Broadcaster()
    application.state.broadcaster = broadcaster

    loop = asyncio.get_running_loop()

    # Close all SSE connections immediately when a shutdown signal arrives.
    # Must happen HERE (before yield) so it fires before uvicorn waits for
    # connections to drain — otherwise broadcaster.close() in the teardown
    # below can never be reached (deadlock).
    def _make_handler(sig: int):
        # Grab uvicorn's already-registered asyncio handler so we can chain it.
        existing = loop._signal_handlers.get(sig)

        def _handler():
            broadcaster.close()
            if existing is not None:
                existing._run()

        return _handler

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _make_handler(sig))
    except (NotImplementedError, AttributeError):
        # Windows: loop.add_signal_handler is not available.
        # Uvicorn's own CTRL+C handling will eventually trigger lifespan
        # teardown via force_exit, which hits broadcaster.close() below.
        pass

    yield

    broadcaster.close()


app = FastAPI(
    title="TACS Log Streamer",
    description="Receive, cache, and stream log events in real-time via SSE.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

app.include_router(ingest.router)
app.include_router(stream.router)
app.include_router(auth.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "connections": app.state.broadcaster.connection_count,
        "cached_events": len(app.state.cache.snapshot()),
        "require_auth": settings.require_auth,
        "providers": settings.configured_providers,
    }
