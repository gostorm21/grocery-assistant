"""Event log model for audit trail and observability."""

import enum
from datetime import datetime

from sqlalchemy import Integer, DateTime, Enum, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ActionType(str, enum.Enum):
    """Types of actions that can be logged."""

    # Write operations
    ADD_ITEM = "add_item"
    REMOVE_ITEM = "remove_item"
    CLEAR_LIST = "clear_list"
    FINALIZE_ORDER = "finalize_order"
    UPDATE_INGREDIENT = "update_ingredient"
    ADD_RECIPE = "add_recipe"
    ADD_RECIPE_NOTE = "add_recipe_note"
    ADD_MEAL = "add_meal"
    REMOVE_MEAL = "remove_meal"
    GENERATE_LIST = "generate_list"
    COMPLETE_MEAL_PLAN = "complete_meal_plan"
    UPDATE_PREFERENCE = "update_preference"
    ADD_PANTRY_ITEM = "add_pantry_item"
    UPDATE_PANTRY_ITEM = "update_pantry_item"
    REMOVE_PANTRY_ITEM = "remove_pantry_item"
    RESOLVE_KROGER = "resolve_kroger"
    CONFIRM_KROGER = "confirm_kroger"
    ADD_TO_CART = "add_to_cart"
    CHECK_OFF_ITEM = "check_off_item"
    # Read operations (optional analytics)
    READ_CONTEXT = "read_context"


class EventLog(Base):
    """Audit trail for tool executions."""

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    related_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<EventLog(id={self.id}, action={self.action_type.value})>"
