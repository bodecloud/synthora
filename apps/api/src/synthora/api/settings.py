"""Platform settings from environment (R-ODR-6, R-LDR-1/2)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = frozenset({"", "change-me", "secret", "changeme"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYNTHORA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./synthora.db"
    redis_url: str = "redis://localhost:6379/0"
    auth_mode: str = "none"  # none | session
    secret_key: str = "change-me"
    token_ttl_seconds: int = 60 * 60 * 24 * 7
    allow_registrations: bool = True
    max_concurrent_researches: int = 3
    cors_origins: str = "*"
    mcp_dns_rebinding_protection: bool = False
    mcp_allowed_hosts: str = ""  # comma-separated Host patterns, e.g. localhost:*,api.example.com:*
    mcp_allowed_origins: str = ""  # comma-separated Origin patterns when rebinding protection is on

    def assert_secure_for_auth(self) -> None:
        """Refuse to boot session auth with a forgeable default JWT secret."""
        if self.auth_mode == "session" and self.secret_key in _INSECURE_SECRETS:
            raise RuntimeError(
                "SYNTHORA_SECRET_KEY must be set to a non-default value "
                "when SYNTHORA_AUTH_MODE=session"
            )


settings = Settings()
