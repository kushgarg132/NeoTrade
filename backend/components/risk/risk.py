import logging

logger = logging.getLogger(__name__)


class RiskRules:
    @staticmethod
    def calculate_position_size(
        account_size: float,
        risk_per_trade_percent: float,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """
        Calculates position size based on risk amount.
        Risk Amount = Account Size * Risk %
        Position Size = Risk Amount / (Entry - Stop Loss)
        """
        if entry_price <= stop_loss:
            # Short trade logic or invalid
             if entry_price > stop_loss: # Long
                 pass
             else: # Short
                 risk_per_share = stop_loss - entry_price
                 if risk_per_share <= 0: return 0.0
                 risk_amount = account_size * (risk_per_trade_percent / 100)
                 return risk_amount / risk_per_share

        risk_per_share = entry_price - stop_loss
        if risk_per_share <= 0:
            return 0.0
            
        risk_amount = account_size * (risk_per_trade_percent / 100)
        return risk_amount / risk_per_share

    @staticmethod
    def check_exposure_limit(
        current_exposure: float,
        max_exposure: float,
        new_position_value: float
    ) -> bool:
        return (current_exposure + new_position_value) <= max_exposure
