"""Configuration for the Trino MCP server, loaded from environment variables."""
import json
import logging
from pathlib import Path
from typing import Optional, Union

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_SYSTEM_CATALOGS = frozenset({"system", "jmx", "memory"})


class Config(BaseSettings):
    # Connection
    trino_host: str
    trino_port: int = 8080
    trino_scheme: str = "https"  # "https" or "http"

    # Auth — "none", "basic", or "jwt"
    trino_auth: str = "basic"
    trino_user: str
    trino_password: str = ""
    trino_jwt_token: str = ""

    # TLS verification: "true" → True, "false" → False, "/path/ca.crt" → str path
    trino_verify: Union[bool, str] = True

    # Query behavior
    trino_max_rows: int = 100

    # Optional session defaults (unqualified SQL resolves to these)
    trino_default_catalog: Optional[str] = None
    trino_default_schema: Optional[str] = None

    # Catalog descriptions for the list_catalogs tool.
    catalog_descriptions_raw: str = Field(default="{}", alias="CATALOG_DESCRIPTIONS")

    # Optional overlay: relationships, metrics, glossary, entity_aliases (not columns).
    semantic_overlay_path: Optional[Path] = Field(default=None, alias="SEMANTIC_OVERLAY_PATH")

    # Introspection filters (csv).
    introspect_catalogs: Optional[str] = Field(default=None, alias="INTROSPECT_CATALOGS")
    introspect_exclude_schemas: str = Field(
        default="information_schema,pg_catalog,sys",
        alias="INTROSPECT_EXCLUDE_SCHEMAS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    @field_validator("trino_auth")
    @classmethod
    def validate_auth(cls, v: str) -> str:
        if v not in ("none", "basic", "jwt"):
            raise ValueError(f"TRINO_AUTH must be 'none', 'basic', or 'jwt', got {v!r}")
        return v

    @field_validator("trino_verify", mode="before")
    @classmethod
    def parse_verify(cls, v: object) -> Union[bool, str]:
        if isinstance(v, bool):
            return v
        s = str(v).strip()
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        return s

    @model_validator(mode="after")
    def check_auth_credentials(self) -> "Config":
        if self.trino_auth == "basic" and not self.trino_password:
            raise ValueError("TRINO_PASSWORD is required when TRINO_AUTH=basic")
        if self.trino_auth == "jwt" and not self.trino_jwt_token:
            raise ValueError("TRINO_JWT_TOKEN is required when TRINO_AUTH=jwt")
        return self

    @property
    def use_auth(self) -> bool:
        return self.trino_auth != "none"

    @property
    def catalog_descriptions(self) -> dict[str, str]:
        try:
            result = json.loads(self.catalog_descriptions_raw)
            if not isinstance(result, dict):
                raise ValueError("CATALOG_DESCRIPTIONS must be a JSON object")
            return result
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("CATALOG_DESCRIPTIONS is invalid, falling back to {}: %s", e)
            return {}

    @property
    def introspect_catalog_allowlist(self) -> set[str] | None:
        if not self.introspect_catalogs:
            return None
        return {c.strip() for c in self.introspect_catalogs.split(",") if c.strip()}

    @property
    def introspect_excluded_schemas(self) -> set[str]:
        return {s.strip().lower() for s in self.introspect_exclude_schemas.split(",") if s.strip()}

    def should_introspect_catalog(self, catalog: str) -> bool:
        if catalog.lower() in _SYSTEM_CATALOGS:
            return False
        allow = self.introspect_catalog_allowlist
        if allow is not None:
            return catalog in allow
        return True
