"""Configuration management with pydantic-settings and validation."""

from pydantic_settings import BaseSettings
from pydantic import field_validator


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
    user_id_l: str

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @field_validator("*", mode="before")
    @classmethod
    def check_not_empty(cls, v, info):
        """Validate that required environment variables are not empty."""
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
            self.user_id_l: "L",
        }


def get_settings() -> Settings:
    """Load and validate settings from environment.

    Raises:
        ValidationError: If required environment variables are missing or invalid.
    """
    return Settings()
