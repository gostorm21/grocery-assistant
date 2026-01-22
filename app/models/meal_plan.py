"""Meal plan model for weekly meal planning."""

import enum
from datetime import date

from sqlalchemy import Integer, Date, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class MealPlanStatus(enum.Enum):
    """Status of a meal plan."""

    PLANNING = "planning"
    FINALIZED = "finalized"
    COMPLETED = "completed"


class MealPlan(Base, TimestampMixin):
    """Model for storing weekly meal plans."""

    __tablename__ = "meal_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    meals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[MealPlanStatus] = mapped_column(
        Enum(MealPlanStatus), default=MealPlanStatus.PLANNING, nullable=False
    )

    def __repr__(self) -> str:
        return f"<MealPlan(id={self.id}, week_start={self.week_start_date}, status={self.status.value})>"
