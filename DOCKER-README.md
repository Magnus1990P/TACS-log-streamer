# Docker Deployment Guide

This guide covers deploying the OAuth2 Log Streamer using Docker and Docker Compose with an Nginx reverse proxy.

## Quick Start

### 1. Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed
- [Docker Compose](https://docs.docker.com/compose/install/) installed
- Git cloned repository

### 2. Configure Environment

Copy the example environment file and configure your OAuth2 providers:

```bash
copy .env.example .env
```

Edit `.env` with your OAuth2 credentials for Microsoft and/or Kanidm. Docker Compose will use these values as environment variables for the containers.

### 3. Development Mode (HTTP Only)

For development with hot-reloading and HTTP:

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

Access the application at: **http://localhost**

### 4. Production Mode (HTTPS)

For production with HTTPS, you need SSL certificates.

#### Option A: Self-signed certificates (testing only)

```bash
# Create ssl directory
mkdir ssl

# Generate self-signed certificate (for testing only)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/privkey.pem -out ssl/fullchain.pem \
  -subj "/CN=localhost"
```

#### Option B: Let's Encrypt certificates (recommended for production)

Use certbot to obtain real certificates:

```bash
# Stop nginx if running
# docker-compose down

# Obtain certificates (standalone mode)
certbot certonly --standalone -d your-domain.com

# Copy certificates to ssl directory
mkdir -p ssl
cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ssl/
cp /etc/letsencrypt/live/your-domain.com/privkey.pem ssl/
```

Then start the services:

```bash
docker-compose up -d
```

Access the application at: **https://your-domain.com**

### 5. Access Endpoints

| Endpoint | URL | Access |
|----------|-----|--------|
| Web UI | `http(s)://localhost` or `http(s)://your-domain.com` | Public |
| Health Check | `http(s)://localhost/health` | Public |
| OAuth2 Login | `http(s)://localhost/auth/login/{provider}` | Public |
| OAuth2 Callback | `http(s)://localhost/auth/callback` | Public |
| User Info | `http(s)://localhost/public/userinfo` | Authenticated |
| Log Stream | `http(s)://localhost/public/stream?token=...` | Authenticated |
| **Internal API** | `http://<docker-host>:8000/internal` | **Internal Only** |

**Important:** The `/internal` endpoint is **NOT accessible via nginx** - it's blocked by the reverse proxy configuration. To access it:

- From another container on the same Docker network: `http://app:8000/internal`
- From the host machine: `http://localhost:8000/internal` (if you expose port 8000)

### 6. Sending Logs to Internal Endpoint

From within the Docker network (another container):

```bash
# Using curl from another container
curl -X POST http://app:8000/internal \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: your-api-key" \
  -d '{"level": "INFO", "message": "Test log", "source": "docker"}'
```

From the host machine (if you expose port 8000):

```bash
curl -X POST http://localhost:8000/internal \
  -H "Content-Type: application/json" \
  -H "X-Internal-API-Key: your-api-key" \
  -d '{"level": "INFO", "message": "Test log", "source": "host"}'
```

## Configuration

### Environment Variables

All environment variables from `.env` are passed as environment variables to the containers via Docker Compose's variable substitution. The nginx container uses its own configuration files.

### Customizing Nginx

- **Main config**: `nginx/nginx.conf` - Main nginx configuration
- **Additional configs**: `nginx/conf.d/` - Additional server blocks
- **SSL certificates**: `ssl/` - Place your certificates here

### Customizing Docker

- **Dockerfile**: Customize the Python image and dependencies
- **docker-compose.yml**: Main compose file
- **docker-compose.override.yml**: Development overrides (loaded automatically)
- **docker-compose.prod.yml**: Production overrides (use with `-f` flag)

## Security Considerations

### 1. Internal Endpoint Protection

The nginx configuration **blocks all `/internal*` endpoints** from public access. These endpoints are only accessible:
- From other containers on the `backend` network
- From the host machine (if port 8000 is exposed)

### 2. HTTPS

Always use HTTPS in production. The nginx configuration automatically:
- Redirects HTTP to HTTPS (if SSL certificates are present)
- Uses modern TLS protocols (TLS 1.2+)
- Implements strong ciphers
- Enables SSL stapling

### 3. JWT Secret

Ensure your `JWT_SECRET_KEY` is strong and kept secret. Generate a new one:

```bash
openssl rand -hex 32
```

### 4. Internal API Key

Set `INTERNAL_API_KEY` to protect the `/internal` endpoint:

```bash
# Generate a strong API key
openssl rand -hex 32
```

Then add to your `.env`:

```
INTERNAL_API_KEY=your-generated-api-key
```

### 5. OAuth2 Client Secrets

Keep your OAuth2 client secrets (`MICROSOFT_CLIENT_SECRET`, `KANIDM_CLIENT_SECRET`) secure. Never commit them to version control.

## Deployment Scenarios

### Scenario 1: Local Development

```bash
# Start with hot-reload
docker-compose up -d

# Access at http://localhost
```

### Scenario 2: Production on Single Server

```bash
# Generate SSL certificates
mkdir ssl
# ... obtain certificates ...

# Start services
docker-compose up -d

# Access at https://your-domain.com
```

### Scenario 3: Production with Custom Domain

1. Update `nginx/nginx.conf` and set `server_name` to your domain
2. Obtain SSL certificates for your domain
3. Start services: `docker-compose up -d`

### Scenario 4: Internal Network Access

To allow internal services to send logs:

```yaml
# In docker-compose.yml, expose port 8000
services:
  app:
    ports:
      - "8000:8000"
```

Then internal services can POST to `http://<server-ip>:8000/internal`.

**Security Note:** Only expose port 8000 on a private internal network, never on the public internet.

## Monitoring

### Health Checks

Both containers have health checks:

```bash
# Check container health
docker inspect --format='{{json .State.Health}}' oidc-log-streamer
docker inspect --format='{{json .State.Health}}' oidc-log-streamer-nginx
```

### Logs

```bash
# View app logs
docker-compose logs app

# View nginx logs
docker-compose logs nginx

# View all logs with follow
docker-compose logs -f
```

### Metrics

The `/health` endpoint returns:
- Application status
- Active connections count
- Queue size
- Active sessions

## Troubleshooting

### Problem: Nginx returns 502 Bad Gateway

**Cause:** Nginx can't connect to the app container.

**Solution:**
1. Check if app container is running: `docker ps`
2. Check app health: `docker-compose logs app`
3. Wait for health check to pass (can take 10-30 seconds)
4. Check network connectivity: `docker exec -it oidc-log-streamer-nginx ping app`

### Problem: OAuth2 redirects not working

**Cause:** OAuth2 callback URLs don't match.

**Solution:** Ensure your OAuth2 provider's callback URL is set to `https://your-domain.com/auth/callback`.

### Problem: Static files not loading

**Solution:** The app serves static files via FastAPI. If nginx is blocking them:
1. Check nginx config for `/static/` location
2. Verify files are in the `static/` directory
3. Restart containers: `docker-compose restart`

### Problem: /internal endpoint is accessible publicly

**Cause:** This should not happen with the provided nginx config.

**Solution:** Check that:
1. nginx config has the `location ~ ^/(internal|admin)` block
2. nginx container is running
3. You're accessing via nginx (port 80/443), not directly to app (port 8000)

### Problem: Docker build fails

**Solution:**
1. Check requirements.txt exists
2. Ensure all dependencies are available
3. Try cleaning build cache: `docker-compose build --no-cache`

## Updates

To update the application:

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## Backup

Important files to backup:
- `.env` - Configuration
- `ssl/` - SSL certificates
- Database files (if applicable)

```bash
# Backup configuration
 tar -czvf backup.tar.gz .env ssl/
```

## Cleanup

```bash
# Stop and remove containers, networks, volumes
docker-compose down -v

# Remove images
docker-compose rm

# Remove all unused Docker objects
docker system prune -a
```
