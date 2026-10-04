"""Approximate Indian NSE equity brokerage + tax cost model, applied per fill
by SimulatedExecutionClient. Rates below match the commonly published
discount-broker schedule (e.g. Zerodha's charge sheet, zerodha.com/charges)
for NSE equity as of this rework -- no network access here to re-verify
against a live current charge sheet, so treat these as approximate, not
authoritative; flagged in task-6-report.md per the brief's ask.

- Brokerage: flat Rs 20 per executed order, or 0.03% of turnover, whichever
  is lower.
- STT (Securities Transaction Tax): 0.1% of turnover on both buy and sell
  for delivery (CNC); 0.025% of turnover on the sell side only for
  intraday (MIS).
- Exchange transaction charges (NSE): 0.00297% of turnover.
- SEBI charges: Rs 10 per crore (1e7) of turnover -- negligible at retail
  size, included anyway for correctness.
- Stamp duty: 0.015% of turnover, buy side only (same rate for CNC and MIS
  -- it's a state duty on the purchase instrument, not an intraday/delivery
  distinction).
- GST: 18% on (brokerage + exchange transaction charges + SEBI charges).
"""

from typing import Literal

from backend.core.models import Side

_BROKERAGE_FLAT = 20.0
_BROKERAGE_PCT = 0.0003
_STT_DELIVERY_PCT = 0.001
_STT_INTRADAY_SELL_PCT = 0.00025
_EXCHANGE_TXN_PCT = 0.0000297
_SEBI_CHARGE_PER_CRORE = 10.0
_STAMP_DUTY_BUY_PCT = 0.00015          # delivery
_STAMP_DUTY_INTRADAY_BUY_PCT = 0.00003  # intraday
_GST_PCT = 0.18


def calculate_indian_costs(
    price: float,
    quantity: float,
    side: Side,
    product: Literal["CNC", "MIS"],
) -> float:
    """Total brokerage + statutory charges for one fill, in rupees, rounded
    to paise (2 decimal places)."""
    turnover = price * quantity
    is_buy = side == Side.BUY

    brokerage = min(_BROKERAGE_FLAT, turnover * _BROKERAGE_PCT)

    if product == "MIS":
        stt = 0.0 if is_buy else turnover * _STT_INTRADAY_SELL_PCT
    else:
        stt = turnover * _STT_DELIVERY_PCT

    exchange_txn_charges = turnover * _EXCHANGE_TXN_PCT
    sebi_charges = turnover * _SEBI_CHARGE_PER_CRORE / 1e7
    stamp_rate = _STAMP_DUTY_INTRADAY_BUY_PCT if product == "MIS" else _STAMP_DUTY_BUY_PCT
    stamp_duty = turnover * stamp_rate if is_buy else 0.0
    gst = _GST_PCT * (brokerage + exchange_txn_charges + sebi_charges)

    total = brokerage + stt + exchange_txn_charges + sebi_charges + stamp_duty + gst
    return round(total, 2)
