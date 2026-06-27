# Kubernetes Deployment for TACS Log Streamer

## Quick Start

### 1. Create the secret

First, create the Kubernetes secret with your actual credentials:

```bash
kubectl create secret generic tacs-log-streamer-secrets \
  --from-literal=JWT_SECRET_KEY=your-secret-key \
  --from-literal=MICROSOFT_CLIENT_ID=your-microsoft-client-id \
  --from-literal=MICROSOFT_CLIENT_SECRET=your-microsoft-client-secret \
  --from-literal=KANIDM_CLIENT_ID=your-kanidm-client-id \
  --from-literal=KANIDM_CLIENT_SECRET=your-kanidm-client-secret \
  --from-literal=INTERNAL_API_KEY=your-internal-api-key
```

### 2. Configure OAuth Providers

Edit `configmap.yaml` to set your OAuth provider URLs, or add them to the secret.

### 3. Configure Ingress

Edit `ingress.yaml` to set your domain name and configure TLS if needed.

### 4. Deploy

```bash
# Apply the configuration
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml  # Only if not using kubectl create
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# Apply ingress (if using ingress controller)
kubectl apply -f k8s/ingress.yaml
```

### 5. Verify

```bash
kubectl get pods
kubectl get svc
kubectl get ingress

# View logs
kubectl logs -f deployment/tacs-log-streamer
```

## Accessing the Application

Once deployed:
- Public interface: `http://<your-ingress-host>/public`
- Health check: `http://<your-ingress-host>/health`
- Internal endpoint: Only accessible from within the cluster at `http://tacs-log-streamer:8000/internal`

## Security Notes

1. **Internal endpoint**: The `/internal` endpoint should NOT be exposed publicly. It's only accessible within the cluster by default.

2. **OAuth callbacks**: Ensure your OAuth provider's callback URLs include your ingress host (e.g., `https://logs.yourdomain.com/auth/callback`)

3. **Session cookies**: The ingress is configured with sticky sessions for OAuth flow. Adjust the `nginx.ingress.kubernetes.io/affinity` annotation based on your ingress controller.

4. **TLS**: Uncomment the TLS section in `ingress.yaml` and configure cert-manager or provide your own TLS certificate.

## Scaling

To scale the deployment:

```bash
kubectl scale deployment tacs-log-streamer --replicas=3
```

## Updates

When you push changes to the main branch, the GitHub Actions workflow will build a new Docker image. To update the deployment:

```bash
# Update the image in deployment.yaml if needed
kubectl apply -f k8s/deployment.yaml

# Or roll out a restart
kubectl rollout restart deployment/tacs-log-streamer
```
