from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Cache
    cache_max_events: int = 200

    # Internal ingest authentication (leave empty to allow all)
    internal_api_key: Optional[str] = None
    internal_api_key_header: str = "X-Internal-API-Key"

    # Branding — URL or path to a logo shown in the header.
    # Use /static/logo.svg for a file mounted into the container.
    brand_logo_url: Optional[str] = None

    # Stream authentication — set to True to require OAuth2 for /stream
    require_auth: bool = False

    # Session secret (used for OAuth2 flow)
    session_secret: str = "change-me-in-production"

    # JWT (for the short-lived token issued after OAuth2)
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Microsoft Entra ID
    microsoft_client_id: Optional[str] = None
    microsoft_client_secret: Optional[str] = None
    microsoft_tenant_id: Optional[str] = None

    @property
    def microsoft_discovery_url(self) -> Optional[str]:
        if not self.microsoft_client_id or not self.microsoft_tenant_id:
            return None
        base = "https://login.microsoftonline.com"
        return f"{base}/{self.microsoft_tenant_id}/v2.0/.well-known/openid-configuration"

    # Kanidm OIDC
    kanidm_client_id: Optional[str] = None
    kanidm_client_secret: Optional[str] = None
    kanidm_base_url: str = "https://kanidm.example.com"

    @property
    def kanidm_discovery_url(self) -> Optional[str]:
        if not self.kanidm_client_id:
            return None
        return (
            f"{self.kanidm_base_url}/oauth2/openid"
            f"/{self.kanidm_client_id}/.well-known/openid-configuration"
        )

    @property
    def configured_providers(self) -> list[str]:
        providers = []
        if self.microsoft_client_id:
            providers.append("microsoft")
        if self.kanidm_client_id:
            providers.append("kanidm")
        return providers


settings = Settings()
