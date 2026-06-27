"""
FastAPI Server with OAuth2 Authentication
- /internal endpoint: receives log events (internal use only)
- /public endpoint: authenticated streaming of log events to users

Supports:
- Microsoft Entra ID (Azure AD) OAuth2
- Kanidm OIDC provider

Deployment Note:
- Only /public* and /auth* endpoints should be publicly accessible
- /internal* endpoints should be internal-only (not exposed to internet)
"""

from fastapi import FastAPI, Depends, HTTPException, Request, status, Query
from fastapi.security import OAuth2AuthorizationCodeBearer
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict, List, Optional, Set
import asyncio
import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

# OAuth2 and JWT handling
from jose import JWTError, jwt
from passlib.context import CryptContext

# Authlib for OAuth2 client
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from starlette.middleware.sessions import SessionMiddleware

# --- Configuration ---
BASE_DIR = Path(__file__).parent

# OAuth configuration - only Microsoft and Kanidm
# Read configuration from environment variables (not from .env file)
config = Config()
oauth = OAuth(config)

# Register OAuth2 providers

# Microsoft Entra ID (Azure AD)
oauth.register(
    name='microsoft',
    client_id=config.get('MICROSOFT_CLIENT_ID', ''),
    client_secret=config.get('MICROSOFT_CLIENT_SECRET', ''),
    authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
    authorize_params=None,
    access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
    refresh_token_url=None,
    client_kwargs={'scope': 'openid email profile'},
    jwks_uri='https://login.microsoftonline.com/common/discovery/v2.0/keys',
    issuer='https://login.microsoftonline.com/{tenantid}/v2.0',
)

# Kanidm OIDC
oauth.register(
    name='kanidm',
    client_id=config.get('KANIDM_CLIENT_ID', ''),
    client_secret=config.get('KANIDM_CLIENT_SECRET', ''),
    authorize_url=config.get('KANIDM_AUTHORIZE_URL', 'https://kanidm.example.com/oauth2/authorize'),
    authorize_params=None,
    access_token_url=config.get('KANIDM_TOKEN_URL', 'https://kanidm.example.com/oauth2/token'),
    refresh_token_url=None,
    client_kwargs={'scope': 'openid email profile'},
    jwks_uri=config.get('KANIDM_JWKS_URI', 'https://kanidm.example.com/oauth2/jwks'),
    issuer=config.get('KANIDM_ISSUER', 'https://kanidm.example.com'),
)

# JWT Configuration
SECRET_KEY = config.get('JWT_SECRET_KEY', 'your-secret-key-change-in-production')
ALGORITHM = config.get('JWT_ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE_MINUTES = int(config.get('ACCESS_TOKEN_EXPIRE_MINUTES', 60))

# Internal API Key Authentication
INTERNAL_API_KEY = config.get('INTERNAL_API_KEY', None)
INTERNAL_API_KEY_HEADER = config.get('INTERNAL_API_KEY_HEADER', 'X-Internal-API-Key')

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    tokenUrl="token",
    authorizationUrl="authorize"
)

# In-memory storage for sessions, log events, and active connections
user_sessions: Dict[str, Dict] = {}  # session_id -> user_info
log_queue: asyncio.Queue = asyncio.Queue()
active_connections: Dict[str, asyncio.Queue] = {}  # user_id -> queue

app = FastAPI(
    title="OAuth2 Secured Log Streamer",
    description="FastAPI server with OAuth2 authentication for log streaming",
    version="1.0.0"
)

# Add session middleware for OAuth flow
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")


# --- Models ---
class LogEvent(BaseModel):
    """Model for log events received on /internal endpoint"""
    level: str = "INFO"  # INFO, WARNING, ERROR, DEBUG, CRITICAL
    message: str
    source: Optional[str] = None
    timestamp: Optional[str] = None
    tags: Optional[List[str]] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[str] = None


class User(BaseModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    picture: Optional[str] = None
    provider: Optional[str] = None


# --- Utility Functions ---
def create_access_token(data: dict, expires_delta: Optional[float] = None):
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = time.time() + expires_delta
    else:
        expire = time.time() + (ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_internal_api_key(api_key: Optional[str] = None, request: Optional[Request] = None) -> bool:
    """
    Verify the internal API key for /internal endpoint authentication.
    
    If INTERNAL_API_KEY is not set, authentication is skipped (for development).
    If set, the request must include a matching API key in the header.
    
    Returns True if authenticated, raises HTTPException if not.
    """
    # If no API key is configured, allow all requests (for development/backward compatibility)
    if not INTERNAL_API_KEY:
        return True
    
    # Try to get API key from header
    if request and api_key is None:
        api_key = request.headers.get(INTERNAL_API_KEY_HEADER)
    
    # Check if API key matches
    if not api_key or not secrets.compare_digest(api_key, INTERNAL_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "InternalAPIKey"},
        )
    
    return True


async def verify_token(token: str) -> User:
    """
    Verify JWT token and return user info.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Check if token is expired
        exp = payload.get("exp")
        if exp is not None and time.time() > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return User(
            id=user_id,
            name=payload.get("name"),
            email=payload.get("email"),
            picture=payload.get("picture"),
            provider=payload.get("provider")
        )
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Dependency to get the current authenticated user"""
    return await verify_token(token)


# --- OAuth2 Authorization Flow ---
@app.get("/auth/login/{provider}")
async def login(request: Request, provider: str):
    """
    **PUBLIC** - Redirect to OAuth2 provider for authentication.
    Supported providers: microsoft, kanidm
    """
    # Validate provider
    if provider not in ['microsoft', 'kanidm']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth2 provider: {provider}. Supported: microsoft, kanidm"
        )
    
    # Check if provider is configured
    if provider not in oauth.clients:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth2 provider '{provider}' not configured. Check your environment variables."
        )
    
    # Store the redirect URL in session
    redirect_uri = str(request.url_for("auth_callback"))
    
    # Generate a state token for CSRF protection
    state = os.urandom(16).hex()
    request.session["oauth_state"] = state
    request.session["oauth_provider"] = provider
    
    # Redirect to OAuth2 provider
    client = oauth.create_client(provider)
    authorization_url, state = client.authorize_redirect(
        request=request,
        redirect_uri=redirect_uri,
        state=state
    )
    
    return RedirectResponse(url=authorization_url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """
    **PUBLIC** - OAuth2 callback handler for Microsoft and Kanidm.
    """
    # Get provider from session
    provider = request.session.get("oauth_provider")
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth2 provider not specified in session"
        )
    
    # Validate provider
    if provider not in ['microsoft', 'kanidm']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid OAuth2 provider: {provider}"
        )
    
    # Verify state
    state = request.session.get("oauth_state")
    if not state or state != request.query_params.get("state"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter - possible CSRF attack"
        )
    
    try:
        # Exchange authorization code for access token
        client = oauth.create_client(provider)
        token = await client.authorize_access_token(request=request)
        
        # Get user information from ID token
        userinfo = await client.parse_id_token(request=request, token=token)
        
        # Parse user info based on provider
        if provider == 'microsoft':
            # Microsoft returns claims in id_token
            user = User(
                id=userinfo.get('sub') or userinfo.get('oid'),
                name=userinfo.get('name'),
                email=userinfo.get('email') or userinfo.get('preferred_username'),
                picture=userinfo.get('picture'),
                provider=provider
            )
        elif provider == 'kanidm':
            # Kanidm OIDC
            user = User(
                id=userinfo.get('sub'),
                name=userinfo.get('name'),
                email=userinfo.get('email'),
                picture=userinfo.get('picture'),
                provider=provider
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unknown provider: {provider}"
            )
        
        # Create JWT access token
        access_token = create_access_token(
            {
                "sub": user.id,
                "name": user.name,
                "email": user.email,
                "picture": user.picture,
                "provider": user.provider
            }
        )
        
        # Store user session
        session_id = os.urandom(16).hex()
        user_sessions[session_id] = user.model_dump()
        request.session["access_token"] = access_token
        request.session["user_id"] = user.id
        request.session["session_id"] = session_id
        
        # Redirect to public page with token
        return RedirectResponse(
            url=f"/public?token={access_token}",
            status_code=status.HTTP_303_SEE_OTHER
        )
        
    except Exception as e:
        # Log the error for debugging
        print(f"OAuth2 authentication error with {provider}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth2 authentication failed: {str(e)}"
        )


# --- Internal Endpoint ---
@app.post("/internal", status_code=status.HTTP_200_OK)
async def receive_log_event(request: Request, log: LogEvent):
    """
    **INTERNAL ONLY** - Do not expose this endpoint publicly!
    
    Receives log events from internal services.
    
    Authentication:
    - Optional static API key via header (X-Internal-API-Key by default)
    - Configure via INTERNAL_API_KEY environment variable
    - If not configured, endpoint is open (for development only)
    
    This endpoint should only be accessible from:
    - Local network
    - Internal services
    - Trusted sources
    """
    # Verify API key (if configured)
    verify_internal_api_key(request=request)
    
    # Add timestamp if not provided
    if not log.timestamp:
        log.timestamp = datetime.utcnow().isoformat() + "Z"
    
    # Put the log event in the queue for all connected clients
    await log_queue.put(log.model_dump())
    
    return {"status": "received", "timestamp": log.timestamp}


# --- Public Endpoints ---
@app.get("/public", response_class=HTMLResponse)
async def public_page(request: Request, token: Optional[str] = Query(None)):
    """
    **PUBLIC** - Web interface for log streaming.
    This endpoint is safe to expose publicly.
    """
    context = {
        "request": request,
        "token": token,
        "providers": ["microsoft", "kanidm"]  # Only these two providers
    }
    return templates.TemplateResponse("index.html", context)


@app.get("/public/stream")
async def log_stream(request: Request, token: str):
    """
    **PUBLIC** - Server-Sent Events endpoint for streaming logs.
    Requires valid OAuth2 token (from Microsoft or Kanidm).
    """
    try:
        # Verify the token and get user info
        user = await verify_token(token)
        user_id = user.id
        
        # Create a new queue for this connection if it doesn't exist
        if user_id not in active_connections:
            active_connections[user_id] = asyncio.Queue()
        
        async def event_generator():
            """Generate SSE events for the client"""
            user_queue = active_connections.get(user_id)
            if not user_queue:
                user_queue = asyncio.Queue()
                active_connections[user_id] = user_queue
            
            try:
                while True:
                    # Wait for new log events
                    try:
                        # First, check if there are events in the user's personal queue
                        log_data = await asyncio.wait_for(user_queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # Check global queue
                        try:
                            log_data = await asyncio.wait_for(log_queue.get(), timeout=0.5)
                            # Also put in user's queue so other connections get it too
                            for uid, queue in active_connections.items():
                                if uid != user_id:
                                    try:
                                        queue.put_nowait(log_data)
                                    except asyncio.QueueFull:
                                        pass
                        except asyncio.TimeoutError:
                            # Send a keep-alive message
                            yield "data: {\"keepalive\": true}\n\n"
                            continue
                    
                    # Format as SSE
                    yield f"data: {json.dumps(log_data)}\n\n"
                    
            except asyncio.CancelledError:
                # Client disconnected
                print(f"Client {user_id} disconnected")
            except Exception as e:
                print(f"Error in event generator for {user_id}: {e}")
            finally:
                # Cleanup
                if user_id in active_connections:
                    del active_connections[user_id]
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-User-ID": user_id,
                "X-User-Name": user.name or ""
            }
        )
        
    except HTTPException as e:
        # Re-raise HTTP exceptions (like 401 Unauthorized)
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing request: {str(e)}"
        )


@app.get("/public/userinfo")
async def get_user_info(user: User = Depends(get_current_user)):
    """
    **PUBLIC** - Get information about the current authenticated user.
    """
    return {
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "picture": user.picture,
        "provider": user.provider,
        "authenticated": True
    }


# --- Health Check ---
@app.get("/health")
async def health_check():
    """
    **PUBLIC** - Health check endpoint.
    Safe to expose publicly for monitoring.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "active_connections": len(active_connections),
        "queue_size": log_queue.qsize(),
        "sessions": len(user_sessions),
        "providers": ["microsoft", "kanidm"]
    }


# --- Root redirect ---
@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to public page"""
    return RedirectResponse(url="/public", status_code=status.HTTP_302_FOUND)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    print("=" * 60)
    print("Kanidm/Microsoft OAuth2 Log Streamer")
    print("=" * 60)
    print(f"Server: http://{host}:{port}")
    print(f"Public page: http://{host}:{port}/public")
    print(f"Health check: http://{host}:{port}/health")
    print()
    print("INTERNAL Endpoints (Do NOT expose publicly):")
    print(f"  POST http://{host}:{port}/internal")
    print()
    print("PUBLIC Endpoints (Safe to expose):")
    print(f"  GET  http://{host}:{port}/public")
    print(f"  GET  http://{host}:{port}/public/*")
    print(f"  GET  http://{host}:{port}/auth/*")
    print(f"  GET  http://{host}:{port}/health")
    print()
    print("Configured OAuth2 providers:")
    
    providers = []
    if config.get('MICROSOFT_CLIENT_ID'):
        providers.append("Microsoft Entra ID")
    if config.get('KANIDM_CLIENT_ID'):
        providers.append("Kanidm OIDC")
    
    if providers:
        for provider in providers:
            print(f"  ✓ {provider}")
    else:
        print("  ⚠ None configured - using mock authentication for development")
    
    print()
    print("DEPLOYMENT INSTRUCTIONS:")
    print("  To expose only public endpoints:")
    print("  1. Use a reverse proxy (Nginx/Apache)")
    print("  2. Configure proxy to only forward /public* and /auth* paths")
    print("  3. Keep /internal* endpoints internal-only")
    print("  4. See DEPLOYMENT.md for detailed instructions")
    print("=" * 60)
    
    uvicorn.run(app, host=host, port=port)
