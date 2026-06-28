# TACS Log Streamer

Real-time access control log viewer. A FastAPI server receives log events from access control hardware, caches the last 200, and pushes them instantly to every connected browser via Server-Sent Events (SSE).

```
Access controller  ──POST /internal──▶  FastAPI  ──SSE /stream──▶  Browser
                                           │
                                     deque(maxlen=200)
                                     (replayed to new clients)
```

---

## Event types

The `level` field of each event identifies the type. The UI classifies and colour-codes them automatically.

| level value | Meaning |
|---|---|
| `ACCESS GRANTED` | Card / credential accepted, door released |
| `ACCESS DENIED` | Card / credential rejected |
| `SYSTEM ERROR` | Controller or reader fault |
| `READER HEARTBEAT` | Periodic alive ping from a reader |
| *(anything else)* | Displayed as **Other** |

---

## Log event format

Events are sent as JSON to `POST /internal`.

```json
{
  "level":     "ACCESS GRANTED",
  "message":   "Card read: John Doe",
  "source":    "door-01",
  "timestamp": "2026-06-27T12:34:56.789Z",
  "tags":      ["building-a", "floor-2"]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `level` | string | yes | Event type — see table above |
| `message` | string | yes | Human-readable description |
| `source` | string | no | Reader / controller ID |
| `timestamp` | ISO 8601 string | no | Server assigns UTC time if omitted |
| `tags` | string array | no | Arbitrary labels, stored but not displayed |

### Example — send an event with curl

```bash
curl -X POST http://localhost:8000/internal \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: your-secret-key" \
  -d '{
    "level":   "READER HEARTBEAT",
    "message": "ping",
    "source":  "reader-05"
  }'
```

---

## Project structure

```
TACS-log-streamer/
├── app/
│   ├── main.py               # App factory, lifespan, health endpoint
│   ├── config.py             # All settings (env vars via pydantic-settings)
│   ├── models/
│   │   └── log.py            # LogEvent pydantic model
│   ├── core/
│   │   ├── cache.py          # EventCache — asyncio-safe deque(maxlen=200)
│   │   └── broadcaster.py    # Fan-out SSE events to all connected clients
│   ├── api/
│   │   ├── ingest.py         # POST /internal
│   │   ├── stream.py         # GET /stream (SSE) and GET / (UI)
│   │   └── auth.py           # OAuth2 routes — Microsoft Entra ID, Kanidm
│   └── static/
│       └── index.html        # Single-page log viewer (Jinja2 template)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Running locally

**Requires Python 3.12+**

```bash
# 1 — install dependencies
pip install -r requirements.txt

# 2 — configure (copy and edit)
cp .env.example .env

# 3 — start
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` — the stream starts immediately. No sign-in is required by default (`REQUIRE_AUTH=false`).

---

## Configuration

All settings are read from environment variables (or a `.env` file).

### Server

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `CACHE_MAX_EVENTS` | `200` | Number of events kept in memory and replayed to new clients |

### Ingest authentication

| Variable | Default | Description |
|---|---|---|
| `INTERNAL_API_KEY` | *(empty)* | If set, `POST /internal` requires this key in the header. Leave empty to allow all senders (development only). |
| `INTERNAL_API_KEY_HEADER` | `X-Internal-API-Key` | Header name for the key above |

Generate a strong key: `openssl rand -hex 32`

### Stream authentication

| Variable | Default | Description |
|---|---|---|
| `REQUIRE_AUTH` | `false` | Set to `true` to require an OAuth2 session before the SSE stream is served |
| `SESSION_SECRET` | *must change* | Session cookie signing key |
| `JWT_SECRET` | *must change* | Signing key for the short-lived JWT issued after OAuth2 |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRE_MINUTES` | `60` | JWT lifetime |

### OAuth2 — Microsoft Entra ID

| Variable | Description |
|---|---|
| `MICROSOFT_CLIENT_ID` | App registration client ID |
| `MICROSOFT_CLIENT_SECRET` | App registration client secret |

Register the app at the Azure portal and set the redirect URI to `https://your-domain/auth/callback`.

### OAuth2 — Kanidm

| Variable | Default | Description |
|---|---|---|
| `KANIDM_CLIENT_ID` | | OAuth2 client name as registered in Kanidm |
| `KANIDM_CLIENT_SECRET` | | Client secret (`kanidm system oauth2 show-basic-secret <name>`) |
| `KANIDM_BASE_URL` | `https://kanidm.example.com` | Base URL of your Kanidm instance — all endpoints are discovered automatically via OIDC discovery |

Required scopes: `openid email profile`. Set the redirect URI to `https://your-domain/auth/callback`.

---

## API endpoints

### Public (safe to expose)

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Log viewer UI |
| `GET` | `/stream` | SSE stream — replays last 200 events then goes live |
| `GET` | `/stream?token=<jwt>` | SSE stream with JWT auth (used when `REQUIRE_AUTH=true`) |
| `GET` | `/auth/login/microsoft` | Start Microsoft OAuth2 flow |
| `GET` | `/auth/login/kanidm` | Start Kanidm OAuth2 flow |
| `GET` | `/auth/callback` | OAuth2 redirect handler |
| `GET` | `/auth/logout` | Clear session |
| `GET` | `/health` | Status, connection count, cached event count |

### Internal (never expose publicly)

| Method | Path | Description |
|---|---|---|
| `POST` | `/internal` | Ingest a log event |

### Health response

```json
{
  "status": "ok",
  "connections": 3,
  "cached_events": 187,
  "require_auth": false,
  "providers": ["microsoft"]
}
```

---

## Deploy with Docker

### Build and run

```bash
# copy and fill in secrets
cp .env.example .env

docker compose up -d
```

The container exposes port `8000`. Place a reverse proxy (Nginx, Traefik, Caddy) in front of it for TLS termination.

### Dockerfile summary

- Base image: `python:3.12-slim`
- Copies `requirements.txt` and `app/` only
- Starts: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

### docker-compose.yml

```yaml
services:
  log-streamer:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
```

### Reverse proxy — Nginx example

Keep `/internal` off the internet. Only forward the public routes:

```nginx
server {
    listen 443 ssl;
    server_name logs.example.com;

    # block the ingest endpoint from the public internet
    location /internal {
        deny all;
    }

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;

        # required for SSE — disable proxy buffering
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 3600s;
    }
}
```

Access control hardware on the internal network sends directly to `http://app-host:8000/internal`, bypassing the proxy entirely.

---

## Security checklist

- [ ] Set strong random values for `SESSION_SECRET` and `JWT_SECRET` in production
- [ ] Set `INTERNAL_API_KEY` so only authorised senders can ingest events
- [ ] Block `/internal` at the reverse proxy (see Nginx example above)
- [ ] Terminate TLS at the reverse proxy — never run plain HTTP on the public internet
- [ ] Set `REQUIRE_AUTH=true` if the log stream should not be publicly visible
- [ ] Use HTTPS callback URIs when registering OAuth2 apps with providers
