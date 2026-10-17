"""Approximate Indian NSE options brokerage + tax cost model, applied to an
option premium fill by suggestions/service.py::execute_suggestion. Same
"approximate, not authoritative" posture backend/engine/execution/costs.py
already states about its own equity numbers -- this is a documented
simplification, not the exact regulatory formula (which also depends on
physical vs. cash settlement details this paper-only strategy doesn't
model). See docs/superpowers/specs/2026-09-11-phase-5b-fno-cash-secured-put-design.md.
"""

from backend.core.models import Side

_BROKERAGE_FLAT = 20.0
# NSE options, on premium turnover, the schedule since 1 Oct 2024: STT 0.1%
# on the sell side (it was 0.0625%, and 0.05% here understated it),
# exchange transaction charges 0.03503%, stamp duty 0.003% on the buy side,
# SEBI Rs 10 per crore; GST 18% on brokerage + exchange + SEBI charges.
_STT_SELL_PCT = 0.001
_EXCHANGE_TXN_PCT = 0.0003503
_STAMP_BUY_PCT = 0.00003
_SEBI_CHARGE_PER_CRORE = 10.0
_GST_PCT = 0.18


def calculate_options_costs(premium: float, quantity: float, side: Side) -> float:
    """Total brokerage + statutory charges for one option fill, in rupees,
    rounded to paise. `quantity` is the total contract quantity (lots *
    lot_size), matching Order.quantity's convention for an option Order."""
    turnover = premium * quantity
    brokerage = _BROKERAGE_FLAT
    stt = turnover * _STT_SELL_PCT if side == Side.SELL else 0.0
    exchange_txn_charges = turnover * _EXCHANGE_TXN_PCT
    sebi_charges = turnover * _SEBI_CHARGE_PER_CRORE / 1e7
    stamp_duty = turnover * _STAMP_BUY_PCT if side == Side.BUY else 0.0
    gst = _GST_PCT * (brokerage + exchange_txn_charges + sebi_charges)
    return round(brokerage + stt + exchange_txn_charges + sebi_charges + stamp_duty + gst, 2)
