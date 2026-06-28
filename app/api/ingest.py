import secrets
from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.models.log import LogEvent

router = APIRouter()


def _verify_api_key(request: Request) -> None:
    if not settings.internal_api_key:
        return
    key = request.headers.get(settings.internal_api_key_header)
    if not key or not secrets.compare_digest(key, settings.internal_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

@router.post("/internal", status_code=status.HTTP_202_ACCEPTED)
async def receive_log(request: Request, log: LogEvent):
    _verify_api_key(request)
    event = log.with_timestamp().model_dump()
    request.app.state.cache.add(event)
    request.app.state.broadcaster.publish(event)
    return {"status": "accepted", "timestamp": event["timestamp"] }
