"""
OAuth2 routes and helpers.

Supported providers: Microsoft Entra ID, Kanidm OIDC.
Auth is optional: if REQUIRE_AUTH=false (default), the stream endpoint is
publicly accessible and these routes are only needed if you want to protect it.
"""

import time
from typing import Optional

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from starlette.config import Config

from app.config import settings

router = APIRouter(prefix="/auth")

_starlette_config = Config()
oauth = OAuth(_starlette_config)

oauth.register(
    name="microsoft",
    client_id=settings.microsoft_client_id or "",
    client_secret=settings.microsoft_client_secret or "",
    server_metadata_url=settings.microsoft_discovery_url or "",
    client_kwargs={"scope": "openid email profile"},
)

oauth.register(
    name="kanidm",
    client_id=settings.kanidm_client_id or "",
    client_secret=settings.kanidm_client_secret or "",
    server_metadata_url=settings.kanidm_discovery_url or "",
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)


class User(BaseModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    provider: Optional[str] = None


def _create_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "name": user.name,
        "email": user.email,
        "provider": user.provider,
        "exp": time.time() + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> Optional[User]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("exp", 0) < time.time():
            return None
        return User(
            id=payload["sub"],
            name=payload.get("name"),
            email=payload.get("email"),
            provider=payload.get("provider"),
        )
    except JWTError:
        return None


async def get_current_user_optional(request: Request) -> Optional[User]:
    token = (
        request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.session.get("access_token")
    )
    if not token:
        return None
    return _decode_token(token)


# --- OAuth2 routes ---

@router.get("/login/{provider}")
async def login(request: Request, provider: str):
    if provider not in ("microsoft", "kanidm"):
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    if provider not in settings.configured_providers:
        raise HTTPException(status_code=501, detail=f"Provider '{provider}' not configured")

    request.session["oauth_provider"] = provider

    redirect_uri = str(request.url_for("auth_callback"))
    client = oauth.create_client(provider)
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    provider = request.session.get("oauth_provider")
    if not provider:
        raise HTTPException(status_code=400, detail="No OAuth provider in session")

    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}

    user = User(
        id=userinfo.get("sub") or userinfo.get("oid", ""),
        name=userinfo.get("name"),
        email=userinfo.get("email") or userinfo.get("preferred_username"),
        provider=provider,
    )

    access_token = _create_token(user)
    request.session["access_token"] = access_token

    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
