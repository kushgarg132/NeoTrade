import logging

import pandas as pd
from backend.components.shared.models import Trend

logger = logging.getLogger(__name__)

class TrendDetector:
    @staticmethod
    def detect_trend(df: pd.DataFrame) -> Trend:
        """
        Detects the current trend based on SMA alignment and price action.
        """
        if len(df) < 200:
            return Trend.CHOPPY # Not enough data
            
        current_price = df['close'].iloc[-1]
        sma_50 = df['sma_50'].iloc[-1]
        sma_200 = df['sma_200'].iloc[-1]
        
        # Simple Golden Cross / Death Cross logic + Price location
        if current_price > sma_50 > sma_200:
            return Trend.UP
        elif current_price < sma_50 < sma_200:
            return Trend.DOWN
        else:
            return Trend.CHOPPY

    @staticmethod
    def analyze_market_structure(df: pd.DataFrame, window: int = 5) -> Trend:
        """
        Analyzes Higher Highs/Higher Lows for Uptrend, Lower Lows/Lower Highs for Downtrend.
        """
        # Simplified implementation looking at last few pivots
        # This would require the SupportResistance logic to find pivots first
        # For now, we rely on SMA alignment
        return TrendDetector.detect_trend(df)
