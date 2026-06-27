# Deployment Guide: Exposing Only Public Endpoints

This guide explains how to deploy the OAuth2 Log Streamer so that **only the public endpoints are exposed to the internet**, while keeping internal endpoints accessible only from trusted internal networks.

## 🔒 Security Architecture

### Endpoint Classification

| Endpoint | Type | Should be Public? | Notes |
|----------|------|------------------|-------|
| `/public` | Public | ✅ Yes | Web interface |
| `/public/*` | Public | ✅ Yes | All public sub-paths |
| `/auth/login/*` | Public | ✅ Yes | OAuth2 login flow |
| `/auth/callback` | Public | ✅ Yes | OAuth2 callback |
| `/health` | Public | ✅ Yes | Health check |
| `/internal` | Internal | ❌ No | Log ingestion |
| `/` | Public | ✅ Yes | Redirects to /public |

### Why This Matters

- **`/internal*` endpoints** accept unauthenticated log data - exposing them publicly would allow anyone to inject fake logs
- **`/public*` and `/auth*` endpoints** are designed for public access with proper authentication
- **`/health` endpoint** is safe to expose for monitoring

---

## 🚀 Deployment Options

### Option 1: Reverse Proxy (Recommended)

Use **Nginx** or **Apache** as a reverse proxy to control which endpoints are exposed.

#### Nginx Configuration

```nginx
# Public-facing server configuration
server {
    listen 80;
    server_name your-domain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # SSL Configuration (use Let's Encrypt or your certs)
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    
    # Proxy to FastAPI application
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (if using WebSockets)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # BLOCK internal endpoints from public access
    location ~ ^/(internal|admin) {
        deny all;
        return 403;
    }
    
    # Allow all other endpoints (public, auth, health)
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Nginx Configuration with Path-Based Routing

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Public endpoints - exposed to internet
    location ~ ^/(public|auth|health|$) {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # Block internal endpoints
    location /internal {
        deny all;
        return 403 "Access denied - internal endpoint";
    }
    
    # Default - block everything else
    location / {
        deny all;
        return 403;
    }
}
```

#### Apache Configuration

```apache
<VirtualHost *:443>
    ServerName your-domain.com
    
    SSLEngine on
    SSLCertificateFile /path/to/cert.pem
    SSLCertificateKeyFile /path/to/key.pem
    
    # Proxy to FastAPI
    ProxyPreserveHost On
    ProxyPass / http://localhost:8000/
    ProxyPassReverse / http://localhost:8000/
    
    # Block internal endpoints
    <LocationMatch "/internal">
        Require all denied
    </LocationMatch>
    
    # Allow public endpoints
    <LocationMatch "/(public|auth|health|$)">
        Require all granted
    </LocationMatch>
    
    # Default deny
    <Location /">
        Require all denied
    </Location>
    
</VirtualHost>
```

---

### Option 2: Separate Internal/External Interfaces

Run **two separate FastAPI instances** on different ports/interfaces:

#### Configuration

```bash
# Public server (exposed to internet) - port 8000
uvicorn server:app --host 0.0.0.0 --port 8000

# Internal server (internal only) - port 8001, bound to localhost
uvicorn server:app --host 127.0.0.1 --port 8001
```

#### Modified Server Code

Create a separate internal-only server that only has the `/internal` endpoints:

```python
# internal_server.py
from fastapi import FastAPI
from server import receive_log_event

app = FastAPI(title="Internal Log Receiver")

app.post("/internal")(receive_log_event)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
```

Then modify the main server to connect to the internal server:

```python
# In server.py, modify the internal endpoints to forward to localhost:8001
@app.post("/internal")
async def receive_log_event(log: LogEvent):
    # Forward to internal server
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8001/internal",
            json=log.model_dump()
        )
        return response.json()
```

#### Nginx Configuration

```nginx
# Public endpoints
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        # ... other headers
    }
}

# Internal endpoints (only accessible from localhost)
server {
    listen 8001;
    server_name internal.your-domain.com;
    
    # Only allow connections from localhost
    allow 127.0.0.1;
    deny all;
    
    location /internal {
        proxy_pass http://localhost:8001;
    }
}
```

---

### Option 3: Firewall Rules

Use **firewall rules** to control access at the network level.

#### Linux (iptables)

```bash
# Allow public access to ports 80, 443
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# Allow internal access to port 8001 (internal endpoint)
# Only from trusted internal IPs
sudo iptables -A INPUT -p tcp --dport 8001 -s 192.168.1.0/24 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 8001 -s 10.0.0.0/8 -j ACCEPT

# Block all other access to port 8001
sudo iptables -A INPUT -p tcp --dport 8001 -j DROP

# Save rules
sudo iptables-save > /etc/iptables/rules.v4
```

#### Windows Firewall

```powershell
# Allow public ports
New-NetFirewallRule -DisplayName "Public HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
New-NetFirewallRule -DisplayName "Public HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow

# Allow internal port only from specific subnets
New-NetFirewallRule -DisplayName "Internal Logs" -Direction Inbound -Protocol TCP -LocalPort 8001 -RemoteAddress 192.168.1.0/24 -Action Allow
New-NetFirewallRule -DisplayName "Internal Logs 10.x" -Direction Inbound -Protocol TCP -LocalPort 8001 -RemoteAddress 10.0.0.0/8 -Action Allow

# Block all other access to internal port
New-NetFirewallRule -DisplayName "Block Internal Public" -Direction Inbound -Protocol TCP -LocalPort 8001 -Action Block
```

---

### Option 4: Docker with Traefik (Kubernetes-friendly)

#### docker-compose.yml

```yaml
version: '3.8'

services:
  # Public-facing service
  log-streamer-public:
    image: your-log-streamer:latest
    ports:
      - "8000:8000"
    environment:
      - HOST=0.0.0.0
      - PORT=8000
    networks:
      - public-net
      - internal-net
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.log-streamer.rule=Host(`your-domain.com`)"
      - "traefik.http.routers.log-streamer.entrypoints=https"
      - "traefik.http.routers.log-streamer.tls=true"
      - "traefik.http.routers.log-streamer.tls.certresolver=letsencrypt"
      - "traefik.http.services.log-streamer.loadbalancer.server.port=8000"

  # Internal-only service
  log-streamer-internal:
    image: your-log-streamer:latest
    ports:
      - "8001:8001"
    environment:
      - HOST=0.0.0.0
      - PORT=8001
    networks:
      - internal-net

  # Traefik reverse proxy
  traefik:
    image: traefik:v2.10
    command:
      - "--providers.docker=true"
      - "--entrypoints.http.address=:80"
      - "--entrypoints.https.address=:443"
      - "--certificatesresolvers.letsencrypt.acme.email=admin@your-domain.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
      - "--certificatesresolvers.letsencrypt.acme.httpchallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=http"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock"
      - "./letsencrypt:/letsencrypt"
    networks:
      - public-net

networks:
  public-net:
    driver: bridge
  internal-net:
    driver: bridge
    internal: true  # Only accessible from other containers
```

#### Traefik Middleware (Optional)

Add middleware to block internal endpoints:

```yaml
labels:
  # ... existing labels
  - "traefik.http.middlewares.block-internal.ipwhitelist.sourcerange=192.168.1.0/24,10.0.0.0/8"
  - "traefik.http.routers.log-streamer.middlewares=block-internal"
  - "traefik.http.middlewares.block-internal-paths.pathprefix.match=/internal"
  - "traefik.http.middlewares.block-internal-paths.pathprefix.replaceregex=^/internal.*"
```

---

### Option 5: API Gateway (AWS, Azure, GCP)

If deploying to cloud platforms:

#### AWS API Gateway

```yaml
# serverless.yml (for AWS)
service: log-streamer

provider:
  name: aws
  runtime: python3.9
  region: us-east-1

functions:
  public-api:
    handler: server.handler
    events:
      - http:
          path: /public
          method: get
          cors: true
      - http:
          path: /public/{proxy+}
          method: any
          cors: true
      - http:
          path: /auth/{proxy+}
          method: any
          cors: true
      - http:
          path: /health
          method: get
          cors: true
      - http:
          path: /
          method: get
          cors: true

  # Internal API (private)
  internal-api:
    handler: internal_server.handler
    events:
      - http:
          path: /internal
          method: post
          private: true  # Only accessible within VPC

    vpc:
      securityGroupIds:
        - sg-internal-only
      subnetIds:
        - subnet-private-a
        - subnet-private-b
```

---

## 🛡️ Security Hardening

### 1. Environment Variables

```bash
# Generate strong JWT secret
openssl rand -hex 32

# Set in .env or environment
export JWT_SECRET_KEY="your-64-character-random-string"
export JWT_ALGORITHM="HS256"

# Generate strong internal API key (recommended)
export INTERNAL_API_KEY="$(openssl rand -hex 32)"
export INTERNAL_API_KEY_HEADER="X-Internal-API-Key"
```

### 1b. Internal API Key Authentication

**Secure your `/internal` endpoint with a static API key:**

The `/internal` endpoint now supports optional API key authentication. This is **highly recommended** for production deployments.

**Configuration:**
```bash
# Generate a strong API key (32+ characters)
export INTERNAL_API_KEY="$(openssl rand -hex 32)"

# Optional: Customize the header name
export INTERNAL_API_KEY_HEADER="X-Internal-API-Key"
```

**Usage:**
```bash
# Send log with API key
curl -X POST http://localhost:8000/internal \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: your-api-key-here" \
  -d '{"level": "INFO", "message": "Test log"}'
```

**Important Notes:**
- If `INTERNAL_API_KEY` is **not set**, the endpoint is open (for development/backward compatibility)
- If `INTERNAL_API_KEY` **is set**, all requests must include a matching API key
- Use `secrets.compare_digest()` for constant-time comparison (prevents timing attacks)
- Always use HTTPS when API key authentication is enabled
- Store API keys securely (never in version control)

### 2. TLS/HTTPS Configuration

**Always use HTTPS in production.** Here are several ways to enable TLS:

#### Option A: Reverse Proxy with SSL Termination (Recommended)

Use Nginx, Apache, or Traefik to handle HTTPS at the proxy level (recommended approach).

**Nginx with Let's Encrypt (Certbot):**
```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal test
sudo certbot renew --dry-run

# Certbot will automatically configure Nginx with SSL
```

**Manual Nginx SSL Configuration:**
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # Strong SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Proxy to FastAPI
    location / {
        proxy_pass http://localhost:8000;
        # ... other proxy settings
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}
```

#### Option B: Direct Uvicorn with SSL

Run uvicorn with SSL certificates directly:

```bash
# Generate self-signed certificates for development
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# Run uvicorn with SSL
uvicorn server:app --host 0.0.0.0 --port 443 --ssl-keyfile key.pem --ssl-certfile cert.pem
```

**Note:** For production, use certificates from a trusted CA (Let's Encrypt, DigiCert, etc.) instead of self-signed.

#### Option C: Using Hypercorn (ASGI server with built-in SSL)

```bash
# Install hypercorn
pip install hypercorn

# Run with SSL
hypercorn server:app --bind 0.0.0.0:443 --keyfile key.pem --certfile cert.pem
```

#### Option D: Docker with TLS

```yaml
# docker-compose.yml
services:
  log-streamer:
    image: your-log-streamer:latest
    ports:
      - "443:443"
    volumes:
      - ./certs:/certs:ro
    command: uvicorn server:app --host 0.0.0.0 --port 443 --ssl-keyfile /certs/key.pem --ssl-certfile /certs/cert.pem
```

### 3. CORS Configuration

In `server.py`, configure CORS to only allow your domains:

```python
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-domain.com",
        "https://www.your-domain.com",
        # Add other trusted domains
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3. Rate Limiting

Add rate limiting to prevent abuse:

```bash
pip install slowapi
```

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.get("/public/stream")
@limiter.limit("10/minute")
async def log_stream(request: Request, token: str):
    ...
```

### 4. HTTPS Enforcement

Always use HTTPS in production. For development, use:

```python
# In development, you can use HTTP
# In production, ALWAYS use HTTPS

# For local development with HTTPS:
# uvicorn server:app --ssl-keyfile ./key.pem --ssl-certfile ./cert.pem
```

### 5. OAuth2 Security

- **Microsoft**: Register app in Azure Portal, set redirect URI
- **Kanidm**: Configure OIDC client with proper scopes
- **Both**: Use PKCE (Proof Key for Code Exchange) for better security

---

## 📊 Monitoring and Logging

### Health Check Endpoint

The `/health` endpoint returns:

```json
{
    "status": "healthy",
    "timestamp": "2024-01-15T10:30:00Z",
    "active_connections": 5,
    "queue_size": 0,
    "sessions": 3,
    "providers": ["microsoft", "kanidm"]
}
```

Set up monitoring:

```bash
# Check every minute
curl -s http://localhost:8000/health | jq .

# Alert if queue_size > 100 (logs backing up)
# Alert if active_connections = 0 (no users connected)
```

### Log Monitoring

Monitor the log queue size to detect issues:

```python
# Add to your monitoring system
@app.get("/metrics")
async def metrics():
    return {
        "log_queue_size": log_queue.qsize(),
        "active_connections": len(active_connections),
        "memory_usage": get_memory_usage()
    }
```

---

## 🎯 Recommended Production Setup

### Architecture

```
Internet
   │
   ▼
┌─────────────────────┐
│   Reverse Proxy      │  ← Nginx/Apache/Traefik
│   (HTTPS Termination)│
└──────────┬──────────┘
           │
   ┌───────┴───────┐
   │               │
   ▼               ▼
┌─────────┐   ┌─────────┐
│ Public  │   │ Internal│
│ Endpoints│   │ Endpoints│
│ /public │   │ /internal│
│ /auth   │   │ /batch   │
│ /health │   └─────────┘
└─────────┘         ↑
                   │
           ┌───────┴───────┐
           │   Internal     │
           │   Services     │
           │   (Trusted)    │
           └───────────────┘
```

### Step-by-Step Deployment

1. **Prepare Server**
   ```bash
   # Clone and setup
   git clone your-repo
   cd OIDC testsite
   pip install -r requirements.txt
   
   # Configure
   cp .env.example .env
   nano .env  # Edit with your credentials
   ```

2. **Test Locally**
   ```bash
   uvicorn server:app --reload --port 8000
   # Test at http://localhost:8000/public
   ```

3. **Set Up Reverse Proxy**
   ```bash
   # Install Nginx
   sudo apt install nginx
   
   # Configure Nginx (see above)
   sudo nano /etc/nginx/sites-available/log-streamer
   sudo ln -s /etc/nginx/sites-available/log-streamer /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

4. **Set Up Systemd Service**
   ```ini
   # /etc/systemd/system/log-streamer.service
   [Unit]
   Description=OAuth2 Log Streamer
   After=network.target
   
   [Service]
   User=logstreamer
   Group=logstreamer
   WorkingDirectory=/opt/log-streamer
   ExecStart=/usr/bin/uvicorn server:app --host 0.0.0.0 --port 8000
   Restart=always
   RestartSec=5
   Environment=PATH=/usr/bin:/usr/local/bin
   EnvironmentFile=/opt/log-streamer/.env
   
   [Install]
   WantedBy=multi-user.target
   ```
   
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable log-streamer
   sudo systemctl start log-streamer
   sudo systemctl status log-streamer
   ```

5. **Set Up HTTPS**
   ```bash
   # Using Certbot with Let's Encrypt
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.com
   sudo certbot renew --dry-run
   ```

6. **Configure OAuth2 Providers**
   - **Microsoft**: Go to Azure Portal → App Registrations → New Registration
     - Redirect URI: `https://your-domain.com/auth/callback`
     - Platform: Web
     - Grant types: Authorization code
   - **Kanidm**: Configure OIDC client in Kanidm
     - Client ID: `your-kanidm-client-id`
     - Redirect URI: `https://your-domain.com/auth/callback`
     - Scopes: `openid email profile`

7. **Verify Deployment**
   ```bash
   # Check public endpoints
   curl https://your-domain.com/health
   curl -I https://your-domain.com/public
   
   # Verify internal endpoints are blocked
   curl -I https://your-domain.com/internal  # Should return 403
   
   # Test internal endpoints from server
   curl -X POST http://localhost:8000/internal -H "Content-Type: application/json" -d '{"message": "test"}'
   ```

---

## 💡 Troubleshooting

### Common Issues

1. **OAuth2 Callback Not Working**
   - Verify redirect URI matches exactly in provider configuration
   - Check that callback URL is HTTPS in production
   - Ensure state parameter is being preserved

2. **Internal Endpoints Accessible Publicly**
   - Verify Nginx/Apache configuration
   - Test with `curl -I https://your-domain.com/internal`
   - Should return 403 Forbidden

3. **SSE Not Working**
   - Check that Nginx has proper proxy headers:
     ```nginx
     proxy_http_version 1.1;
     proxy_set_header Upgrade $http_upgrade;
     proxy_set_header Connection "upgrade";
     ```
   - Verify no firewalls are blocking the connection

4. **Token Validation Failing**
   - Check JWT_SECRET_KEY is consistent
   - Verify token expiration time
   - Ensure clock is synchronized (NTP)

### Debug Commands

```bash
# Check Nginx logs
sudo tail -f /var/log/nginx/error.log

# Check application logs
journalctl -u log-streamer -f

# Test OAuth2 flow manually
curl -v https://your-domain.com/auth/login/microsoft

# Check what's listening
sudo ss -tulnp | grep 8000
```

---

## ✅ Verification Checklist

Before going live, verify:

- [ ] HTTPS is working (A+ rating on SSL Labs)
- [ ] `/health` returns 200 OK
- [ ] `/public` loads without errors
- [ ] OAuth2 login redirects to provider
- [ ] OAuth2 callback returns to `/public` with token
- [ ] SSE stream works after authentication
- [ ] `/internal` returns 403 when accessed from internet
- [ ] `/internal` works from localhost/internal network
- [ ] CORS headers are correct
- [ ] Rate limiting is configured
- [ ] Monitoring is set up
- [ ] Backups are configured
- [ ] JWT_SECRET_KEY is strong and secret
- [ ] OAuth2 client secrets are secure
