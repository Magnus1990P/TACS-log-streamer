# OAuth2 Secured Log Streamer

A FastAPI server with OAuth2 authentication that receives log events on an internal endpoint and streams them to authenticated users via Server-Sent Events (SSE).

## Features

- **OAuth2 Authentication**: Supports Microsoft Entra ID (Azure AD) and Kanidm OIDC
- **Two Endpoints**:
  - `/internal`: Receives log events (no auth required, **INTERNAL ONLY**)
  - `/public`: Authenticated streaming of log events to users
- **Server-Sent Events (SSE)**: Real-time log streaming to authenticated clients
- **JWT Tokens**: Secure token-based authentication
- **Responsive UI**: Modern web interface with real-time updates
- **Security**: Designed for secure deployment with only public endpoints exposed

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure OAuth2

Copy the example environment file and configure your OAuth2 providers:

```bash
copy .env.example .env
```

Edit `.env` with your **Microsoft Entra ID** and **Kanidm OIDC** client credentials.

**Microsoft Setup:**
- Register app at: https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/NewApplication
- Set redirect URI: `https://your-domain.com/auth/callback`

**Kanidm Setup:**
- Configure OIDC client in your Kanidm server
- Set redirect URI: `https://your-domain.com/auth/callback`
- Required scopes: `openid email profile`

### 3. Run the Server

```bash
python server.py
```

Or with uvicorn directly:

```bash
uvicorn server:app --reload --port 8000
```

### 4. Access the Application

- **Public Page**: `http://localhost:8000/public` (safe to expose publicly)
- **Health Check**: `http://localhost:8000/health` (safe to expose publicly)
- **Internal API**: `POST http://localhost:8000/internal` (**DO NOT expose publicly**)

## Endpoints

### Internal Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/internal` | Receive log events (API key authentication optional) |

**Request Body for `/internal`:**
```json
{
    "level": "INFO",
    "message": "Application started",
    "source": "my-app",
    "tags": ["startup", "system"]
}
```

### Public Endpoints (Require OAuth2 Auth)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/public` | Web interface for log streaming |
| GET | `/public/stream?token=...` | SSE endpoint for streaming logs |
| GET | `/public/userinfo` | Get current user information |
| GET | `/auth/login/{provider}` | Initiate OAuth2 login flow |
| GET | `/auth/callback` | OAuth2 callback handler |
| GET | `/health` | Health check endpoint |

### OAuth2 Flow

1. User visits `/public`
2. Clicks "Sign in with [Provider]" 
3. Redirected to `/auth/login/{provider}`
4. Redirected to OAuth2 provider's authorization page
5. After authentication, redirected to `/auth/callback`
6. Server creates JWT token and redirects to `/public?token=...`
7. Client connects to `/public/stream?token=...` for SSE

## Usage Examples

### Send Log Events (cURL)

```bash
# Single log event (without API key - for development)
curl -X POST http://localhost:8000/internal \
  -H "Content-Type: application/json" \
  -d '{"level": "INFO", "message": "Hello World", "source": "test-app"}'

# Single log event with API key (for production)
curl -X POST http://localhost:8000/internal \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: your-api-key-here" \
  -d '{"level": "INFO", "message": "Hello World", "source": "test-app"}'

```

### Connect to Log Stream (JavaScript)

```javascript
// After OAuth2 authentication
const accessToken = 'your-jwt-token';

// Connect to SSE stream
const eventSource = new EventSource(`/public/stream?token=${encodeURIComponent(accessToken)}`);

eventSource.onmessage = function(event) {
    const logData = JSON.parse(event.data);
    console.log('New log:', logData);
    
    // Handle keep-alive messages
    if (logData.keepalive) {
        return;
    }
    
    // Process log data
    console.log(`[${logData.timestamp}] ${logData.level} ${logData.message}`);
};

eventSource.onerror = function(error) {
    console.error('Connection error:', error);
    // Implement reconnection logic
};
```

### Get User Information

```bash
curl http://localhost:8000/public/userinfo \
  -H "Authorization: Bearer your-jwt-token"
```

## Project Structure

```
OIDC testsite/
├── server.py           # Main FastAPI application (Microsoft + Kanidm)
├── main.py            # Simple version (standalone, mock auth for dev)
├── config.py          # Configuration management
├── requirements.txt   # Python dependencies
├── .env.example       # Environment configuration template
├── DEPLOYMENT.md      # Detailed deployment guide
├── templates/
│   └── index.html     # Web interface
├── static/            # Static files (CSS, JS, images)
└── README.md          # This file
```

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8000 | Server port |
| `HOST` | 0.0.0.0 | Server host |
| `JWT_SECRET_KEY` | - | Secret key for JWT signing |
| `JWT_ALGORITHM` | HS256 | JWT algorithm (HS256, RS256) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60 | Token expiration time |
| `INTERNAL_API_KEY` | - | Static API key for /internal endpoint (optional) |
| `INTERNAL_API_KEY_HEADER` | X-Internal-API-Key | Header name for API key |
| `MICROSOFT_CLIENT_ID` | - | Microsoft Entra ID client ID |
| `MICROSOFT_CLIENT_SECRET` | - | Microsoft Entra ID client secret |
| `KANIDM_CLIENT_ID` | - | Kanidm OIDC client ID |
| `KANIDM_CLIENT_SECRET` | - | Kanidm OIDC client secret |
| `KANIDM_AUTHORIZE_URL` | - | Kanidm OAuth2 authorize URL |
| `KANIDM_TOKEN_URL` | - | Kanidm OAuth2 token URL |
| `KANIDM_JWKS_URI` | - | Kanidm JWKS URI |
| `KANIDM_ISSUER` | - | Kanidm issuer URL |

## Security Considerations

1. **JWT Secret Key**: Always use a strong, random secret key in production
2. **HTTPS**: Always use HTTPS in production to protect tokens in transit
3. **CORS**: Configure CORS properly for your production environment
4. **Token Storage**: Store tokens securely (HttpOnly cookies for web apps)
5. **CSRF Protection**: The OAuth2 flow includes state parameter for CSRF protection
6. **Input Validation**: All inputs are validated using Pydantic models
7. **Internal Endpoint**: Configure `INTERNAL_API_KEY` to protect the `/internal` endpoint

### Internal Endpoint Security

The `/internal` endpoint now supports **optional static API key authentication**:

- **Development mode**: If `INTERNAL_API_KEY` is not set, the endpoint accepts all requests
- **Production mode**: Set `INTERNAL_API_KEY` to require API key authentication via the `X-Internal-API-Key` header
- **Generate a strong key**: `openssl rand -hex 32`

### TLS/HTTPS

**Always use HTTPS in production.** Options:

1. **Reverse Proxy (Recommended)**: Use Nginx, Apache, or Traefik with SSL termination
2. **Direct Uvicorn**: `uvicorn server:app --ssl-keyfile key.pem --ssl-certfile cert.pem`
3. **Hypercorn**: `hypercorn server:app --keyfile key.pem --certfile cert.pem`

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed TLS configuration.

## Development

For development without OAuth2 providers, the server includes mock authentication:

```javascript
// In the web interface, click "Connect with Mock Token"
// This creates a development token that allows testing
```

## Production Deployment

For production, consider:

1. **Use ASGI Server**: `uvicorn server:app --workers 4 --host 0.0.0.0 --port 80`
2. **Reverse Proxy**: Use Nginx or Apache as reverse proxy with HTTPS
3. **Environment Variables**: Set all sensitive configuration via environment variables
4. **Monitoring**: Add monitoring for the log queue and active connections
5. **Rate Limiting**: Consider adding rate limiting to prevent abuse

### 🔒 Important: Secure Deployment

**Only expose these endpoints publicly:**
- `/public*` - Web interface and authenticated streaming
- `/auth*` - OAuth2 authentication flow
- `/health` - Health check
- `/` - Redirects to /public

**Keep these endpoints internal-only:**
- `/internal` - Log ingestion (configure `INTERNAL_API_KEY` for authentication)

**See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.**

### Recommended Setup

```
Internet → [Reverse Proxy: Nginx/Apache/Traefik] → FastAPI Server
                      ↑
                 [HTTPS Termination]
                 [Path-based Routing]
                 [Blocks /internal* from public]

Internal Network → FastAPI Server:8000/internal (allowed)
```

For complete deployment guide with Nginx, Apache, Docker, Kubernetes, and cloud provider examples, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## Testing

### Manual Testing

1. Start the server: `python server.py`
2. Open browser: `http://localhost:8000/public`
3. Click "Connect with Mock Token"
4. Click "Send Test Log" to generate test logs
5. Watch logs appear in real-time

### API Testing with cURL

```bash
# Send a test log
curl -X POST http://localhost:8000/internal \
  -H "Content-Type: application/json" \
  -d '{"level": "INFO", "message": "Test message", "source": "curl"}'

# Check health
curl http://localhost:8000/health
```

## Alternatives

### Simple Version (No External Dependencies)

The `main.py` file contains a simpler version that doesn't require Authlib:

```bash
python main.py
```

This version uses mock OAuth2 authentication for development.

## Troubleshooting

### Common Issues

1. **OAuth2 not working**: Ensure your callback URLs are registered with the provider
2. **CORS errors**: Configure CORS properly or use same origin
3. **Connection issues**: Check that the server is running and accessible
4. **Token errors**: Verify your JWT secret key matches across instances

### Debug Mode

Add `--reload` flag to uvicorn for automatic reloads during development:

```bash
uvicorn server:app --reload --port 8000
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a pull request
