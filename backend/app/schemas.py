from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

class TradeCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    direction: str
    outcome: str
    pnl: float = Field(allow_inf_nan=False)
    notes: str = Field(default="", max_length=2000)
    created_at: datetime | None = None
    client_ref: str | None = Field(default=None, min_length=16, max_length=64, pattern="^[A-Za-z0-9_-]+$")
    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value): return value.strip().upper()
    @field_validator("direction")
    @classmethod
    def valid_direction(cls, value):
        value = value.strip().lower()
        if value not in {"buy", "sell"}: raise ValueError("Direction must be buy or sell.")
        return value
    @field_validator("outcome")
    @classmethod
    def valid_outcome(cls, value):
        value = value.strip().lower()
        if value not in {"win", "loss", "breakeven"}: raise ValueError("Outcome must be win, loss or breakeven.")
        return value

class LegacyJournalRow(TradeCreate):
    date: str = Field(default="", max_length=40)
    source_ref: str = Field(min_length=16, max_length=64, pattern="^[A-Za-z0-9_-]+$")
    record_wallet: bool = False


class LegacyJournalImportRequest(BaseModel):
    source_id: str = Field(min_length=16, max_length=64, pattern="^[A-Za-z0-9_-]+$")
    rows: list[LegacyJournalRow] = Field(max_length=500)


class LegacyJournalImportResponse(BaseModel):
    imported: int
    total: int


class TradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    symbol: str
    direction: str
    outcome: str
    pnl: float
    notes: str

class PreferenceWrite(BaseModel):
    value: str = Field(max_length=4000)

class PreferenceResponse(BaseModel):
    key: str
    value: str

class AIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)

class AIChatResponse(BaseModel):
    reply: str
    model: str

class WalletTransactionCreate(BaseModel):
    transaction_type: str
    amount: float = Field(gt=0, le=1000000000, allow_inf_nan=False)
    description: str = Field(default="", max_length=240)
    @field_validator("transaction_type")
    @classmethod
    def valid_transaction_type(cls, value):
        value = value.strip().lower()
        if value not in {"deposit", "withdrawal"}:
            raise ValueError("Transaction type must be deposit or withdrawal.")
        return value

class WalletTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    transaction_type: str
    amount: float
    description: str
    trade_id: int | None

class WalletSummaryResponse(BaseModel):
    balance: float
    deposits: float
    withdrawals: float
    trading_pnl: float

class TelegramSendRequest(BaseModel):
    bot_token: str = Field(min_length=20, max_length=200)
    chat_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4096)

class TelegramConnectRequest(BaseModel):
    bot_token: str = Field(min_length=20, max_length=200)
    chat_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=40)

class AutoSignalSettingsRequest(BaseModel):
    enabled: bool = False
    interval_seconds: int = Field(default=180, ge=60, le=3600)
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT","ETHUSDT","SOLUSDT"], max_length=4)

    @field_validator("symbols")
    @classmethod
    def valid_auto_signal_symbols(cls, values):
        allowed = {"BTCUSDT","ETHUSDT","SOLUSDT","XAUUSD"}
        normalized = list(dict.fromkeys(str(value).upper() for value in values))
        if not normalized or any(value not in allowed for value in normalized):
            raise ValueError("Select one or more supported crypto markets or XAUUSD.")
        return normalized

class SignalSettingsRequest(BaseModel):
    primary: str = Field(default="5", pattern="^(1|5|15|30|50|60)$")
    trend: str = Field(default="60", pattern="^(15|30|60|240)$")
    enabled: list[str] = Field(default_factory=lambda: ["60","30","15","5","1"], max_length=6)
    risk_percent: float = Field(default=1.0, gt=0, le=5, allow_inf_nan=False)
    min_score: int = Field(default=7, ge=6, le=10)
    @field_validator("enabled")
    @classmethod
    def valid_timeframes(cls, values):
        allowed={"1","5","15","30","50","60"}
        if not values or any(str(x) not in allowed for x in values):
            raise ValueError("Choose one or more supported analysis timeframes.")
        return list(dict.fromkeys(str(x) for x in values))
