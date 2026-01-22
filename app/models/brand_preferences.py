"""Brand preferences model for storing preferred brands."""

import enum

from sqlalchemy import Integer, String, Enum
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class BrandConfidence(enum.Enum):
    """Confidence level for brand preference."""

    CONFIRMED = "confirmed"
    INFERRED = "inferred"


class BrandPreference(Base, TimestampMixin):
    """Model for storing brand preferences.

    Maps generic item names to preferred brands.
    Example: "milk" -> "Organic Valley"
    """

    __tablename__ = "brand_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generic_item: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    preferred_brand: Mapped[str] = mapped_column(String(255), nullable=False)
    kroger_product_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[BrandConfidence] = mapped_column(
        Enum(BrandConfidence), default=BrandConfidence.CONFIRMED, nullable=False
    )

    def __repr__(self) -> str:
        return f"<BrandPreference(item='{self.generic_item}', brand='{self.preferred_brand}')>"
