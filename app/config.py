"""Configuration management with pydantic-settings and validation."""

from pydantic_settings import BaseSettings
from pydantic import field_validator


# Fields that are optional (app works without them)
OPTIONAL_FIELDS = {
    "kroger_client_id",
    "kroger_client_secret",
    "kroger_redirect_uri",
    "kroger_location_id",
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Slack Configuration
    slack_bot_token: str
    slack_app_token: str
    slack_channel_id: str

    # Anthropic Configuration
    anthropic_api_key: str

    # Database Configuration
    database_url: str

    # User ID Mapping
    user_id_erich: str
    user_id_lauren: str

    # Kroger API (optional — app works without them)
    kroger_client_id: str = ""
    kroger_client_secret: str = ""
    kroger_redirect_uri: str = ""
    kroger_location_id: str = ""

    # Agentic Loop Settings
    max_tool_turns: int = 15
    status_checkpoint_turn: int = 10
    enable_prompt_caching: bool = True
    user_timezone: str = "America/Denver"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_database_url(cls, v):
        """Railway uses postgres:// but SQLAlchemy requires postgresql://."""
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    @field_validator("*", mode="before")
    @classmethod
    def check_not_empty(cls, v, info):
        """Validate that required environment variables are not empty."""
        # Skip validation for optional fields and fields with defaults
        optional_with_defaults = OPTIONAL_FIELDS | {
            "max_tool_turns", "status_checkpoint_turn",
            "enable_prompt_caching", "user_timezone",
        }
        if info.field_name in optional_with_defaults:
            return v if v is not None else ""
        if v is None:
            raise ValueError(f"Required environment variable is not set")
        if isinstance(v, str) and v.strip() == "":
            raise ValueError(f"Required environment variable is empty")
        return v

    @property
    def user_mapping(self) -> dict[str, str]:
        """Return mapping of Slack user IDs to display names."""
        return {
            self.user_id_erich: "Erich",
            self.user_id_lauren: "Lauren",
        }


def get_settings() -> Settings:
    """Load and validate settings from environment.

    Raises:
        ValidationError: If required environment variables are missing or invalid.
    """
    return Settings()
