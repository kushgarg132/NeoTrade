"""Model-priced options for backtests. There is no history of option
premiums to replay, so a backtest of an options strategy stands in for both
the instrument master (which contracts are listed) and the premium source
(what each costs) with this: monthly contracts around the current spot,
priced by Black-Scholes on the underlying's own recent volatility.

That is a model, not the market -- no volatility smile, no bid-ask spread,
no liquidity limit -- so a result from it is optimistic about fills. It is
what lets an options strategy be put through the same backtest gate as
everything else instead of skipping it.
"""

import math
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from backend.engine.session import IST
from backend.instruments.models import Instrument
from backend.options.pricing import black_scholes_call, black_scholes_put

STRIKES_EACH_SIDE = 5
# ponytail: 5-minute bars assumed (75 a session); the vol estimate is off by
# sqrt(bar ratio) on any other intraday timeframe.
BARS_PER_YEAR = 252 * 75
VOL_WINDOW_BARS = 75 * 5  # the last five sessions
MIN_VOL = 0.10
EXPIRY_CLOSE = time(15, 30)


def _last_thursday(year: int, month: int) -> date:
    # ponytail: NSE's stock-option expiry weekday has changed before (it is
    # a Tuesday from late 2025); a fixed last Thursday is close enough for a
    # model, not for placing real orders.
    last = date(year, month, monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - 3) % 7)


def _expiry(today: date) -> date:
    """The monthly expiry at least one day out, like the live sizer picks."""
    expiry = _last_thursday(today.year, today.month)
    if (expiry - today).days < 1:
        year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        expiry = _last_thursday(year, month)
    return expiry


def _strike_step(spot: float) -> float:
    """A round step near 1% of spot (1, 2, 2.5, 5 x a power of ten), about
    where NSE lists strikes."""
    raw = spot * 0.01
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)


class ModelOptions:
    """Pass one as both `master` and `premium_source` to runner.run, and
    call observe() with every bar before the runner sees it."""

    def __init__(self, lot_sizes: dict[str, int]) -> None:
        self._lot_sizes = lot_sizes
        self._closes: dict[str, list[float]] = defaultdict(list)
        self._now: datetime | None = None

    def observe(self, symbol: str, bar) -> None:
        closes = self._closes[symbol]
        closes.append(bar.close)
        del closes[:-(VOL_WINDOW_BARS + 1)]
        self._now = bar.timestamp

    async def option_contracts(self, underlying: str, option_type: str) -> list[Instrument]:
        closes = self._closes.get(underlying)
        lot_size = self._lot_sizes.get(underlying)
        if not closes or not lot_size or self._now is None:
            return []
        spot, expiry = closes[-1], _expiry(self._now.astimezone(IST).date())
        step = _strike_step(spot)
        atm = round(spot / step) * step
        return [
            Instrument(
                exchange="NFO", tradingsymbol=f"{underlying}{expiry:%y%b}{strike:g}{option_type}".upper(),
                name=underlying, instrument_token=0, exchange_token=0, instrument_type=option_type,
                segment="NFO-OPT", lot_size=lot_size, tick_size=0.05,
                expiry=datetime.combine(expiry, time(0, 0)), strike=strike,
            )
            for strike in (atm + k * step for k in range(-STRIKES_EACH_SIDE, STRIKES_EACH_SIDE + 1))
        ]

    def _volatility(self, closes: list[float]) -> float:
        returns = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
        if len(returns) < 2:
            return MIN_VOL
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return max(math.sqrt(variance * BARS_PER_YEAR), MIN_VOL)

    async def __call__(self, contract: Instrument) -> float | None:
        closes = self._closes.get(contract.name)
        if not closes or self._now is None:
            return None
        expires = datetime.combine(contract.expiry.date(), EXPIRY_CLOSE, tzinfo=IST)
        days = (expires - self._now.astimezone(IST)).total_seconds() / 86400
        price = black_scholes_call if contract.instrument_type == "CE" else black_scholes_put
        premium = price(closes[-1], contract.strike, days, self._volatility(closes))
        premium = round(premium / 0.05) * 0.05
        return premium if premium > 0 else None
