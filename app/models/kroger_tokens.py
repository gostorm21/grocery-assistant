"""Kroger OAuth token storage model."""

from sqlalchemy import Integer, String, Float
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class KrogerToken(Base, TimestampMixin):
    """Single-row table for persisting Kroger OAuth tokens across restarts."""

    __tablename__ = "kroger_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    access_token: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    token_expiry: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<KrogerToken(id={self.id})>"
