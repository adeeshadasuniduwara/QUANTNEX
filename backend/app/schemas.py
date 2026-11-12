from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if value.count("@") != 1 or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address.")
        return value

class LoginRequest(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class TradeCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    direction: str
    outcome: str
    pnl: float
    notes: str = Field(default="", max_length=2000)
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
    amount: float = Field(gt=0, le=1000000000)
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

class SignalSettingsRequest(BaseModel):
    primary: str = Field(default="5", pattern="^(1|5|15|30|50|60)$")
    trend: str = Field(default="60", pattern="^(15|30|60|240)$")
    enabled: list[str] = Field(default_factory=lambda: ["60","30","15","5","1"], max_length=6)
    risk_percent: float = Field(default=1.0, gt=0, le=5)
    min_score: int = Field(default=7, ge=6, le=10)
    @field_validator("enabled")
    @classmethod
    def valid_timeframes(cls, values):
        allowed={"1","5","15","30","50","60"}
        if not values or any(str(x) not in allowed for x in values):
            raise ValueError("Choose one or more supported analysis timeframes.")
        return list(dict.fromkeys(str(x) for x in values))
