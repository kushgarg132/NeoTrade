"""Engine-core data models: plain Pydantic models / dataclasses, no I/O.

Shared by backtest, paper, and (later) live trading -- these are the only
shapes that flow through the engine loop (backend/engine/runner.py).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.instruments.models import Instrument


class Side(str, Enum):
    """Compare by identity (`side == Side.BUY`) or, once a value has round-
    tripped through something serialized (a dict/JSON), by `.value` -- never
    against a bare string literal. `SignalType.BUY` serializing to "buy" but
    being compared against "BUY" was a real P0 bug in this codebase; don't
    repeat it here."""

    BUY = "BUY"
    SELL = "SELL"


class Bar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_token: int
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    # A catch-up bar from before the run started (a live feed's first poll):
    # strategies see it so indicators warm up, but the runner never trades on
    # it -- its price is history, not one anyone can deal at now.
    warmup: bool = False


@dataclass(frozen=True)
class Intent:
    """A strategy's raw trade idea, before any sizing/risk is applied.

    `__post_init__` makes "no rule hit, no intent" structural: a strategy
    literally cannot construct an Intent without at least one reason code
    and a strength in [0, 1], rather than relying on every strategy author
    remembering the convention.
    """

    symbol: str
    side: Side
    strength: float
    reason_codes: list[str]
    stop_hint: Optional[float] = None
    target_hint: Optional[float] = None
    # "CSP" (cash-secured put) marks an Intent that size_intents dispatches
    # to backend/options/sizing.py instead of the equity stop-distance
    # sizer -- see that module's docstring. None (every existing strategy)
    # means "ordinary equity intent", zero behavior change. "LONG_CALL" /
    # "LONG_PUT" buy an at-the-money option for an intraday move; for those
    # stop_hint/target_hint are levels on the underlying, and the runner
    # closes the option when the underlying reaches either.
    option_flavor: Optional[Literal["CSP", "LONG_CALL", "LONG_PUT"]] = None
    # The strategy that emitted this intent, stamped by the context while that
    # strategy's on_bar runs. None for intents made outside a run (tests,
    # chat): sizing then falls back to the symbol's listed owner.
    strategy: Optional[str] = None
    # Swing built strategies (Phase 18.1): exit after this many trading days held, and trail the
    # stop at close - trail_atr x ATR (a multiple; exit code computes the level from the bars).
    max_hold_days: Optional[int] = None
    trail_atr: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("Intent.reason_codes must not be empty -- no rule hit, no intent")
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"Intent.strength must be within [0, 1], got {self.strength!r}")


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    symbol: str
    side: Side
    quantity: float
    order_type: Literal["MARKET", "LIMIT", "SL-M"]
    limit_price: Optional[float] = None
    # Stop-loss market: becomes a market order once the price crosses this.
    trigger_price: Optional[float] = None
    status: Literal["PENDING", "FILLED", "CANCELLED", "REJECTED"] = "PENDING"
    # CNC (delivery) vs MIS (intraday, margin) -- Task 6's Indian cost model
    # (backend/engine/execution/costs.py) selects STT/brokerage rates by
    # this field. Defaults to MIS since that's what an intraday-mode
    # strategy's forced square-off order always is; size_intents (Task 6)
    # sets it explicitly per order from the owning strategy's spec.mode.
    product: Literal["CNC", "MIS", "NRML"] = "MIS"
    # Which strategy emitted this order -- None means "not attributable to
    # a live-eligible strategy", which is also the correct default: an
    # order with no strategy_name can never be routed live by
    # RoutingExecutionClient (backend/engine/execution/routing.py), only
    # to paper. Set by size_intents from owner_by_symbol.
    strategy_name: Optional[str] = None
    # The path that placed it when that is not the strategy itself, e.g.
    # "autopilot:engine". strategy_name stays the strategy whose idea it
    # was, so the paper gate and learning credit the right one.
    via: Optional[str] = None
    # The proposal an approved order executes; the trade it opens carries it
    # so an exit can find that proposal's stop and target.
    suggestion_id: Optional[str] = None
    # The signal that produced the order: strength, reason_codes and the
    # composite score. Copied onto the trade it opens, so closed trades can
    # be judged by setup (backend/learning). None for orders no signal made.
    context: Optional[dict] = None
    # The listed F&O contract for an option order (its NFO row from the
    # instrument master); None for every equity order. Brokers that can
    # place option orders read the contract off it; any other broker
    # adapter must refuse it (see supports_options on the adapters).
    contract: Optional[Instrument] = None

    def whole_quantity(self) -> int:
        """Equities trade in whole shares -- every broker adapter's
        place_order needs an int, never a silently-truncated fraction.
        size_intents already only ever produces whole-share quantities, so
        this should never actually raise; it exists to make that assumption
        visible instead of a fractional quantity quietly rounding down at
        the broker call."""
        if self.quantity != int(self.quantity):
            raise ValueError(f"Order quantity must be a whole number of shares, got {self.quantity}")
        return int(self.quantity)


Venue = Literal["paper", "live"]


class Fill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    timestamp: datetime
    # brokerage + taxes + slippage; Task 6 owns the real cost model, this
    # task just carries the field.
    costs: float = 0.0
    # Where the fill happened: "live" only when a real broker reported it
    # (BrokerExecutionClient). Everything the simulator, an approved
    # suggestion or an expiry settlement produces is paper. The app keeps the
    # two books apart on this field, so real money never reads as practice.
    venue: Venue = "paper"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    # Only set on positions read from a broker's own book (the adapters'
    # get_positions), normalized to NSE/NFO/... and MIS/CNC/NRML. Guardrail
    # square-off (backend/guardrails/square_off.py) refuses any position
    # where either is unknown rather than guess.
    exchange: Optional[str] = None
    product: Optional[str] = None
    # Set by Portfolio.apply from the fill that opened the position. None on
    # broker-book positions and on ledger rows written before venues existed
    # -- the ledger reads those as paper, which is what they all were.
    venue: Optional[Venue] = None


LiveOrderState = Literal[
    "SUBMITTED", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELLED",
]


class BrokerOrderStatus(BaseModel):
    """A broker's own order-status response, normalized to this app's
    LiveOrderState by whichever BrokerAdapter fetched it -- Kite/Upstox/
    Angel One all use different status strings natively (see each
    adapter's docstring for the mapping); nothing outside the adapter
    layer should ever see a broker-native status string."""

    model_config = ConfigDict(extra="forbid")

    broker_order_id: str
    status: LiveOrderState
    filled_quantity: float
    average_price: float


class BrokerTrade(BaseModel):
    """One execution from a broker's own trade book, normalized by whichever
    BrokerAdapter fetched it (or the Console CSV importer). `traded_at` is
    timezone-aware UTC -- every broker reports IST wall-clock, and the
    adapter is where that gets pinned down, never downstream."""

    model_config = ConfigDict(extra="forbid")

    trade_id: str
    order_id: str = ""
    symbol: str
    exchange: str = "NSE"
    side: Side
    quantity: float
    price: float
    traded_at: datetime


class Holding(BaseModel):
    """One long-term holding read from a broker's own portfolio: settled
    shares plus those still in T+1 settlement, or mutual fund units.
    `avg_price` is the broker's cost basis; `last_price` its latest mark
    (None where the broker gave none -- never guessed)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    isin: Optional[str] = None
    name: Optional[str] = None
    exchange: Optional[str] = None
    kind: Literal["STOCK", "ETF", "MF"] = "STOCK"
    quantity: float
    avg_price: float
    last_price: Optional[float] = None
    close_price: Optional[float] = None
    broker: str


# --- Market / research models (moved from the retired backend/components/shared) ---

# Enums
class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"

class Trend(str, Enum):
    UP = "up"
    DOWN = "down"
    CHOPPY = "choppy"

class NewsArticle(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    title: str
    url: str
    source: str
    published_at: datetime
    content: Optional[str] = None
    sentiment: Optional[Sentiment] = None
    sentiment_score: float = 0.0  # -1.0 to 1.0
    impact_score: int = 0  # 1-10
    related_symbols: List[str] = []

class FinancialEvent(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    event_type: str  # earnings, merger, layoff, etc.
    description: str
    date: datetime
    symbols: List[str]
    impact_rating: int

class PriceCandle(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    adj_close: Optional[float] = None
    volume: float

class BacktestResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    start_date: datetime
    end_date: datetime
    total_trades: int
    win_rate: float
    profit_factor: float
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: float
    trades: List[Dict[str, Any]] # List of individual trade details


class CompanyInfo(BaseModel):
    """Comprehensive stock/company information for UI display"""
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    current_price: float
    previous_close: Optional[float] = None
    day_change: Optional[float] = None
    day_change_percent: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    currency: str = "USD"  # Default to USD

    logo_url: Optional[str] = None
    
    # Fundamental Data
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    trailing_eps: Optional[float] = None
    forward_eps: Optional[float] = None
    return_on_equity: Optional[float] = None
    return_on_assets: Optional[float] = None
    revenue_growth: Optional[float] = None
    total_revenue: Optional[float] = None
    total_debt: Optional[float] = None
    total_cash: Optional[float] = None
    ebitda: Optional[float] = None
    operating_margins: Optional[float] = None
    gross_margins: Optional[float] = None


class Watchlist(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    
    user_id: str
    symbols: List[str] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)
