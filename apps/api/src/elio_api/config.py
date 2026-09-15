from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELIO_", env_file=".env", extra="ignore")

    app_name: str = "elio-api"
    environment: str = "development"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://elio:elio@localhost:5432/elio"

    log_level: str = "INFO"
    log_json: bool = True

    cors_origins: list[str] = ["http://localhost:5173"]

    # OIDC/JWT — external IdP in production. Local/dev password login issues
    # Elio-signed tokens when jwt_private_key_pem is set.
    jwt_issuer: str = "https://elio.local/realms/dev"
    jwt_audience: str = "elio-api"
    jwt_algorithm: str = "RS256"
    jwt_public_key_pem: str = ""
    jwt_private_key_pem: str = ""
    auth_enabled: bool = True
    # Allow POST /auth/login with local password hashes. Disable in production
    # when a real OIDC IdP is the only login path.
    allow_password_login: bool = True
    access_token_ttl_seconds: int = 900
    # Local content-addressed evidence root. Replace with S3 backend without domain changes.
    evidence_root: str = "var/evidence"

    # Anti-abuse (KE field reality). 0 disables duration checks (tests/dev).
    min_execution_seconds: int = 120
    min_evidence_bytes: int = 64
    # Reject same content hash reused on another work item by same actor (window hours).
    evidence_reuse_window_hours: int = 72


@lru_cache
def get_settings() -> Settings:
    return Settings()
