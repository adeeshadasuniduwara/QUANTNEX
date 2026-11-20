from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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

class JournalImport(Base):
    """Idempotency ledger for importing legacy browser-only journal rows."""
    __tablename__ = "journal_imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(String(64))
    source_ref: Mapped[str] = mapped_column(String(64))
    trade_id: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("user_id", "source_ref", name="uq_journal_import_source_row"),
    )


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


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    details: Mapped[str] = mapped_column(Text, default="{}")


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="OPEN", index=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)



class StrategyLabRun(Base):
    __tablename__ = "strategy_lab_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    run_type: Mapped[str] = mapped_column(String(20), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    strategy_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

class PersonalGoal(Base):
    __tablename__ = "personal_goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    target_amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    initial_amount: Mapped[float] = mapped_column(Float, default=0)
    image_url: Mapped[str] = mapped_column(Text, default="")
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    achieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    certificate_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    certificate_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class GoalContribution(Base):
    __tablename__ = "goal_contributions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("personal_goals.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source: Mapped[str] = mapped_column(String(48), default="manual_real_account")
    note: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

class PaperTradeEvent(Base):
    __tablename__ = "paper_trade_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("paper_trades.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float, default=0)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class SignalTrade(Base):
    __tablename__ = "signal_trades"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", name="uq_signal_trade_user_fingerprint"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(220))
    source: Mapped[str] = mapped_column(String(32), default="QUANTNEX_VIEW")
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    side: Mapped[str] = mapped_column(String(8))
    timeframe: Mapped[str] = mapped_column(String(8))
    entry_type: Mapped[str] = mapped_column(String(12), default="MARKET")
    entry_price: Mapped[float] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float)
    active_stop_loss: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    tp3: Mapped[float] = mapped_column(Float)
    risk_distance: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    tp1_hit: Mapped[bool] = mapped_column(default=False)
    tp2_hit: Mapped[bool] = mapped_column(default=False)
    tp3_hit: Mapped[bool] = mapped_column(default=False)
    tp1_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tp2_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tp3_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_candle_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_r: Mapped[float] = mapped_column(Float, default=0.0)
    recovery_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    recovery_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SignalTradeEvent(Base):
    __tablename__ = "signal_trade_events"
    __table_args__ = (UniqueConstraint("trade_id", "event_key", name="uq_signal_trade_event_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("signal_trades.id", ondelete="CASCADE"), index=True)
    event_key: Mapped[str] = mapped_column(String(48))
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[float] = mapped_column(Float)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    telegram_attempts: Mapped[int] = mapped_column(Integer, default=0)
    telegram_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class TelegramDelivery(Base):
    """Persistent idempotency ledger for outbound Telegram notifications."""
    __tablename__ = "telegram_deliveries"
    __table_args__ = (UniqueConstraint("user_id", "notification_key", name="uq_telegram_delivery_user_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notification_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="sending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)



class OrderFlowObservation(Base):
    """Bounded, public Binance Spot order-flow feature snapshot for research replay."""
    __tablename__ = "order_flow_observations"
    __table_args__ = (
        UniqueConstraint("market_type", "symbol", "sample_bucket", name="uq_order_flow_market_symbol_minute"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_type: Mapped[str] = mapped_column(String(24), index=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    sample_bucket: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    captured_at_epoch_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    last_agg_trade_id: Mapped[int] = mapped_column(BigInteger)
    depth_update_id: Mapped[int] = mapped_column(BigInteger)
    trade_count: Mapped[int] = mapped_column(Integer)
    trade_data_age_seconds: Mapped[float] = mapped_column(Float)
    depth_age_seconds: Mapped[float] = mapped_column(Float)
    delta: Mapped[float] = mapped_column(Float)
    delta_ratio: Mapped[float] = mapped_column(Float)
    cvd_value: Mapped[float] = mapped_column(Float)
    cvd_status: Mapped[str] = mapped_column(String(40))
    session_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_delta_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    spread_bps: Mapped[float] = mapped_column(Float)
    depth_imbalance: Mapped[float] = mapped_column(Float)
    snapshot_json: Mapped[str] = mapped_column(Text)
