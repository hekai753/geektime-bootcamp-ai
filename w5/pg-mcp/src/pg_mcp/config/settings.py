"""Configuration management for PostgreSQL MCP Server.

This module defines all configuration settings using Pydantic for validation
and type safety. Configuration is loaded from environment variables with
sensible defaults.
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """Database connection configuration (PostgreSQL or MySQL)."""

    model_config = SettingsConfigDict(
        env_prefix="DATABASE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    db_type: Literal["postgres", "mysql"] = Field(
        default="postgres",
        description="Database engine type (DATABASE_DB_TYPE)",
    )
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    name: str = Field(default="postgres", description="Database name")
    user: str = Field(default="postgres", description="Database user")
    password: str = Field(default="", description="Database password")

    # Connection pool settings
    min_pool_size: int = Field(default=5, ge=1, le=100, description="Minimum pool size")
    max_pool_size: int = Field(default=20, ge=1, le=100, description="Maximum pool size")
    pool_timeout: float = Field(
        default=30.0, ge=1.0, le=300.0, description="Pool acquire timeout in seconds"
    )
    command_timeout: float = Field(
        default=30.0, ge=1.0, le=300.0, description="Command execution timeout in seconds"
    )

    @property
    def dsn(self) -> str:
        """Build PostgreSQL DSN connection string."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sqlglot_dialect(self) -> str:
        """SQL dialect name used by the validator/parser for this database."""
        return "mysql" if self.db_type == "mysql" else "postgres"

    @property
    def safe_dsn(self) -> str:
        """Build DSN with masked password for logging."""
        return f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.name}"


class OpenAIConfig(BaseSettings):
    """OpenAI API configuration.

    The API key is intentionally NOT validated at config load time: the
    server must be able to start (and run tests) without a key, and a key
    is only required when the OpenAI provider is actually invoked. LLM
    clients are responsible for raising LLMError when the key is missing.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENAI_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_key: SecretStr = Field(default=SecretStr(""), description="OpenAI API key")
    model: str = Field(default="gpt-4o-mini", description="Model to use for SQL generation")
    max_tokens: int = Field(default=2000, ge=100, le=4096, description="Maximum tokens in response")
    temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, description="Temperature for response randomness"
    )
    timeout: float = Field(
        default=30.0, ge=5.0, le=120.0, description="API request timeout in seconds"
    )


class AnthropicConfig(BaseSettings):
    """Anthropic Claude API configuration.

    The API key is validated lazily by the LLM client when a provider call
    is actually made (mirrors :class:`OpenAIConfig`).
    """

    model_config = SettingsConfigDict(
        env_prefix="ANTHROPIC_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_key: SecretStr = Field(default=SecretStr(""), description="Anthropic API key")
    auth_token: SecretStr = Field(
        default=SecretStr(""),
        description="Bearer token (ANTHROPIC_AUTH_TOKEN) for Anthropic-compatible gateways",
    )
    base_url: str | None = Field(
        default=None,
        description="Custom API base URL (ANTHROPIC_BASE_URL) for gateways/proxies",
    )
    model: str = Field(default="claude-haiku-4-5", description="Claude model for SQL generation")
    max_tokens: int = Field(default=2000, ge=100, le=8192, description="Maximum tokens in response")
    timeout: float = Field(
        default=30.0, ge=5.0, le=120.0, description="API request timeout in seconds"
    )


class LLMProviderConfig(BaseSettings):
    """Which LLM provider to use for SQL generation and result validation."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    provider: Literal["openai", "anthropic"] = Field(
        default="openai",
        description="LLM provider used for SQL generation (LLM_PROVIDER)",
    )


class SecurityConfig(BaseSettings):
    """Security and access control configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SECURITY_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    blocked_functions: list[str] = Field(
        default_factory=lambda: [
            "pg_sleep",
            "pg_read_file",
            "pg_write_file",
            "lo_import",
            "lo_export",
        ],
        description="List of blocked PostgreSQL functions",
    )
    blocked_tables: list[str] = Field(
        default_factory=list,
        description="Tables that queries may not access (e.g. secrets, api_keys)",
    )
    blocked_columns: list[str] = Field(
        default_factory=list,
        description="Columns that queries may not reference (e.g. password_hash)",
    )
    allow_explain: bool = Field(
        default=False,
        description="Whether EXPLAIN statements are permitted",
    )
    max_rows: int = Field(default=10000, ge=1, le=100000, description="Maximum rows to return")
    max_execution_time: float = Field(
        default=30.0, ge=1.0, le=300.0, description="Maximum query execution time in seconds"
    )
    readonly_role: str | None = Field(
        default=None, description="PostgreSQL role to switch to for read-only access"
    )
    safe_search_path: str = Field(
        default="public", description="Safe search_path to set during query execution"
    )

    @field_validator("blocked_functions", "blocked_tables", "blocked_columns", mode="before")
    @classmethod
    def parse_blocked_list(cls, v: str | list[str]) -> list[str]:
        """Parse comma-separated string or list."""
        if isinstance(v, str):
            return [f.strip() for f in v.split(",") if f.strip()]
        return v


class ValidationConfig(BaseSettings):
    """Query validation configuration."""

    model_config = SettingsConfigDict(
        env_prefix="VALIDATION_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    max_question_length: int = Field(
        default=10000, ge=1, le=50000, description="Maximum question length in characters"
    )

    # Result validation settings
    enabled: bool = Field(default=True, description="Enable result validation using LLM")
    sample_rows: int = Field(
        default=5, ge=1, le=100, description="Number of sample rows to include in validation"
    )
    timeout_seconds: float = Field(
        default=10.0, ge=1.0, le=60.0, description="Result validation timeout in seconds"
    )
    confidence_threshold: int = Field(
        default=70, ge=0, le=100, description="Minimum confidence for acceptable results"
    )


class CacheConfig(BaseSettings):
    """Schema cache configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CACHE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    schema_ttl: int = Field(
        default=3600, ge=60, le=86400, description="Schema cache TTL in seconds"
    )
    max_size: int = Field(default=100, ge=1, le=1000, description="Maximum cache entries")
    enabled: bool = Field(default=True, description="Enable schema caching")


class ResilienceConfig(BaseSettings):
    """Resilience and fault tolerance configuration."""

    model_config = SettingsConfigDict(
        env_prefix="RESILIENCE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts")
    query_rate_limit: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Maximum concurrent queries (RESILIENCE_QUERY_RATE_LIMIT)",
    )
    llm_rate_limit: int = Field(
        default=5,
        ge=1,
        le=1000,
        description="Maximum concurrent LLM calls (RESILIENCE_LLM_RATE_LIMIT)",
    )
    rate_limit_timeout: float = Field(
        default=5.0,
        ge=0.1,
        le=300.0,
        description="Seconds to wait for a rate-limiter slot before rejecting",
    )
    retry_delay: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Initial retry delay in seconds"
    )
    backoff_factor: float = Field(
        default=2.0, ge=1.0, le=10.0, description="Exponential backoff factor"
    )
    circuit_breaker_threshold: int = Field(
        default=5, ge=1, le=100, description="Failures before circuit opens"
    )
    circuit_breaker_timeout: float = Field(
        default=60.0, ge=10.0, le=300.0, description="Circuit breaker timeout in seconds"
    )


class ObservabilityConfig(BaseSettings):
    """Observability and monitoring configuration."""

    model_config = SettingsConfigDict(
        env_prefix="OBSERVABILITY_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    metrics_enabled: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(
        default=9090, ge=1024, le=65535, description="Metrics HTTP server port"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    log_format: Literal["json", "text"] = Field(default="json", description="Log format")


class Settings(BaseSettings):
    """Main application settings aggregating all config sections."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = Field(
        default="development", description="Application environment"
    )

    # Nested configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    #: Additional databases addressable via the request ``database`` field.
    #: Configure through the JSON config file or the DATABASES env variable, e.g.:
    #:   DATABASES='{"shop": {"db_type": "mysql", "host": "...", "name": "shop"}}'
    databases: dict[str, DatabaseConfig] = Field(default_factory=dict)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create global settings instance.

    Returns:
        Settings: The global settings instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset global settings instance. Useful for testing."""
    global _settings
    _settings = None
