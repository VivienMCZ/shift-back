from sqlalchemy import Integer, String, Float, DateTime, func, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from typing import List, Optional, Any
from datetime import datetime
from app.database import Base


class AutoEcole(Base):
    __tablename__ = "auto_ecoles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(nullable=False)
    address: Mapped[Optional[str]] = mapped_column(nullable=True)
    city: Mapped[str] = mapped_column(nullable=False)
    postal_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    lat: Mapped[float] = mapped_column(nullable=False)
    lng: Mapped[float] = mapped_column(nullable=False)
    rating: Mapped[float] = mapped_column(default=0.0)
    price: Mapped[Optional[int]] = mapped_column(nullable=True)
    price_label: Mapped[Optional[str]] = mapped_column(nullable=True)
    speed_level: Mapped[Optional[str]] = mapped_column(nullable=True)
    speed_label: Mapped[Optional[str]] = mapped_column(nullable=True)
    permis_type: Mapped[str] = mapped_column(default="voiture")
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    image_url: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(unique=True, nullable=True)
    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str] = mapped_column(nullable=False)
    age: Mapped[Optional[int]] = mapped_column(nullable=True)
    statut: Mapped[Optional[str]] = mapped_column(nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    otp_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    otp_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Favorite(Base):
    """Auto-école likée (mise en favori) par un utilisateur."""

    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "auto_ecole_id", name="uq_favorite_user_ecole"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    auto_ecole_id: Mapped[int] = mapped_column(ForeignKey("auto_ecoles.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Lib(Base):
    __tablename__ = 'libs'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    fr: Mapped[str] = mapped_column(nullable=False)
    en: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

