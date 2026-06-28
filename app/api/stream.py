import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import settings
from app.api.auth import get_current_user_optional

router = APIRouter()

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "static"))

KEEPALIVE_INTERVAL = 15  # seconds


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _event_stream(request: Request) -> AsyncIterator[str]:
    cache = request.app.state.cache
    broadcaster = request.app.state.broadcaster

    for event in cache.snapshot():
        yield _sse(event)

    yield "event: ready\ndata: {}\n\n"

    async with broadcaster.subscribe() as queue:
        # One persistent task that fires when the server is shutting down.
        # Races against queue.get() each iteration so we exit immediately
        # on SIGTERM/SIGINT rather than waiting for the next keepalive timeout.
        closing = asyncio.create_task(broadcaster.closing.wait())
        try:
            while True:
                get_next = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {get_next, closing},
                    timeout=KEEPALIVE_INTERVAL,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if closing in done or broadcaster.closing.is_set():
                    get_next.cancel()
                    break

                if get_next in done:
                    yield _sse(get_next.result())
                else:
                    # Keepalive timeout — check for client disconnect
                    get_next.cancel()
                    if await request.is_disconnected():
                        break
                    yield ": keepalive\n\n"
        finally:
            closing.cancel()
            try:
                await closing
            except asyncio.CancelledError:
                pass


@router.get("/stream")
async def log_stream(request: Request, user=Depends(get_current_user_optional)):
    if settings.require_auth and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, user=Depends(get_current_user_optional)):
    return _templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "providers": settings.configured_providers,
            "require_auth": settings.require_auth,
            "is_authenticated": user is not None,
            "brand_logo_url": settings.brand_logo_url,
        },
    )
