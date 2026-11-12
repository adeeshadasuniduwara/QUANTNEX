from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utc_now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    trades: Mapped[list["Trade"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    preferences: Mapped[list["Preference"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    symbol: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(8))
    outcome: Mapped[str] = mapped_column(String(16))
    pnl: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    user: Mapped[User] = relationship(back_populates="trades")

class Preference(Base):
    __tablename__ = "preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text)
    user: Mapped[User] = relationship(back_populates="preferences")
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_preference"),)

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    transaction_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(240), default="")
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
