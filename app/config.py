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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @field_validator("*", mode="before")
    @classmethod
    def check_not_empty(cls, v, info):
        """Validate that required environment variables are not empty."""
        # Skip validation for optional fields
        if info.field_name in OPTIONAL_FIELDS:
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
