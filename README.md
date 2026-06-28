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
│   ├── main.py               # App factory, lifespan, signal handlers, health endpoint
│   ├── config.py             # All settings (env vars via pydantic-settings)
│   ├── models/
│   │   └── log.py            # LogEvent pydantic model
│   ├── core/
│   │   ├── cache.py          # EventCache — thread-safe deque(maxlen=200)
│   │   └── broadcaster.py    # Fan-out SSE events; asyncio.Event-based shutdown
│   ├── api/
│   │   ├── ingest.py         # POST /internal
│   │   ├── stream.py         # GET /stream (SSE) and GET / (UI)
│   │   └── auth.py           # OAuth2 routes — Microsoft Entra ID, Kanidm
│   └── static/
│       └── index.html        # Single-page log viewer (Jinja2 template)
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml        # Non-sensitive operational settings
│   ├── secret.yaml           # Auth/OIDC values — fill in, never commit
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml          # Public nginx ingress with TLS
│   └── ingress-tailscale.yaml# Tailscale Funnel ingress
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Running locally

**Requires Python 3.12+**

```bash
# 1 — install dependencies
pip install -r requirements.txt

# 2 — configure
cp .env .env.local   # edit .env.local with your values

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
| `CACHE_MAX_EVENTS` | `200` | Events kept in memory and replayed to new clients |

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

After a successful OAuth2 login the JWT is stored in an httpOnly session cookie. It is never passed via URL query parameters.

### OAuth2 — Microsoft Entra ID

| Variable | Description |
|---|---|
| `MICROSOFT_TENANT_ID` | Directory (tenant) ID — found in Entra ID → Overview |
| `MICROSOFT_CLIENT_ID` | App registration client ID |
| `MICROSOFT_CLIENT_SECRET` | App registration client secret |

Register the app at the Azure portal. Set the redirect URI to `https://your-domain/auth/callback`. All endpoints are discovered automatically from `https://login.microsoftonline.com/<tenant-id>/v2.0/.well-known/openid-configuration`.

### OAuth2 — Kanidm

| Variable | Default | Description |
|---|---|---|
| `KANIDM_CLIENT_ID` | | OAuth2 client name as registered in Kanidm |
| `KANIDM_CLIENT_SECRET` | | Client secret (`kanidm system oauth2 show-basic-secret <name>`) |
| `KANIDM_BASE_URL` | `https://kanidm.example.com` | Base URL of your Kanidm instance |

Required scopes: `openid email profile`. PKCE (S256) is enabled automatically. Set the redirect URI to `https://your-domain/auth/callback`. All endpoints are discovered automatically via OIDC discovery.

---

## API endpoints

### Public (safe to expose)

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Log viewer UI |
| `GET` | `/stream` | SSE stream — replays last 200 events then goes live. Requires a valid session cookie when `REQUIRE_AUTH=true`. |
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
  "providers": ["kanidm"]
}
```

---

## Deploy with Docker

```bash
docker compose up -d
```

The container exposes port `8000`. Place a reverse proxy in front for TLS termination.

### Reverse proxy — Nginx example

Block `/internal` at the proxy so access control hardware can reach it on the internal network while browsers only see the public routes.

```nginx
server {
    listen 443 ssl;
    server_name logs.example.com;

    location /internal {
        deny all;
    }

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;

        # required for SSE
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 3600s;
    }
}
```

---

## Deploy with Kubernetes

All manifests are in the `k8s/` directory.

### Prerequisites

- [cert-manager](https://cert-manager.io) with a `ClusterIssuer` named `letsencrypt-prod` (for the nginx ingress)
- [ingress-nginx](https://kubernetes.github.io/ingress-nginx/) controller
- [Tailscale Kubernetes Operator](https://tailscale.com/kb/1236/kubernetes-operator) (for the Tailscale ingress)

### 1 — Fill in the secret

`k8s/secret.yaml` is gitignored. Edit it with your real values before applying — it must never be committed.

```yaml
stringData:
  INTERNAL_API_KEY:     "your-strong-api-key"
  SESSION_SECRET:       "openssl rand -hex 32"
  JWT_SECRET:           "openssl rand -hex 32"
  KANIDM_CLIENT_ID:     "tacs-log-streamer"
  KANIDM_CLIENT_SECRET: "..."
  KANIDM_BASE_URL:      "https://kanidm.example.com"
```

### 2 — Set the image name

In `k8s/deployment.yaml`, replace `OWNER` with your GitHub organisation or username:

```yaml
image: ghcr.io/OWNER/tacs-log-streamer:latest
```

If the GHCR package is private, create an image pull secret and uncomment the `imagePullSecrets` block in `deployment.yaml`.

### 3 — Set the public hostname

In `k8s/ingress.yaml`, replace `logs.example.com` with your real domain (DNS must point to the ingress controller's external IP).

### 4 — Apply

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml           # nginx + Let's Encrypt TLS
kubectl apply -f k8s/ingress-tailscale.yaml # Tailscale Funnel (optional)
```

### Ingress options

| File | Access | TLS |
|---|---|---|
| `ingress.yaml` | Public internet via nginx | cert-manager / Let's Encrypt |
| `ingress-tailscale.yaml` | Public internet via [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) | Tailscale-managed |

Both can run simultaneously. Remove `tailscale.com/funnel: "true"` from `ingress-tailscale.yaml` to restrict Tailscale access to tailnet members only.

### Scaling note

SSE connections are held in-process. Running more than one replica will split clients across pods — events sent to pod A will not reach clients connected to pod B. Keep `replicas: 1` unless you add a shared message bus (e.g. Redis Pub/Sub).

---

## Security checklist

- [ ] Set strong random values for `SESSION_SECRET` and `JWT_SECRET`
- [ ] Set `INTERNAL_API_KEY` so only authorised senders can ingest events
- [ ] Block `/internal` at the reverse proxy or Kubernetes ingress
- [ ] Terminate TLS — never run plain HTTP on the public internet
- [ ] Set `REQUIRE_AUTH=true` if the log stream should not be publicly visible
- [ ] Use HTTPS callback URIs when registering OAuth2 apps with providers
- [ ] Never commit `k8s/secret.yaml` with real values
