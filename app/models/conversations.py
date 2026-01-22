"""Conversations model for storing chat history."""

import enum
from datetime import datetime

from sqlalchemy import Integer, String, Text, DateTime, Enum, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ConversationStatus(enum.Enum):
    """Status of a conversation message processing."""

    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    API_ERROR = "api_error"


class Conversation(Base):
    """Model for storing conversation history.

    Tracks all messages between users and the assistant.

    context_snapshot structure:
    {
        "shopping_list_size": 12,
        "brand_prefs_count": 5,
        "recent_messages_count": 5,
        "recent_notes_count": 3,
        "input_tokens": 1200,
        "output_tokens": 300
    }
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shopping_list_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("shopping_lists.id"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    user: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assistant_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus), default=ConversationStatus.SUCCESS, nullable=False
    )
    slack_user_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    slack_message_ts: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationship to shopping list
    shopping_list: Mapped["ShoppingList"] = relationship(
        "ShoppingList", back_populates="conversations"
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, user='{self.user}', status={self.status.value})>"
