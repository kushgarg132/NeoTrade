import pandas as pd
import logging
from typing import List, Optional, Tuple

from backend.core.models import Trend

logger = logging.getLogger(__name__)

class Indicators:
    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index (Wilder's smoothing)"""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average"""
        return series.rolling(window=period).mean()

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average"""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Average True Range"""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def vwap(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        volume: pd.Series,
        session: Optional[pd.Series] = None,
    ) -> pd.Series:
        """Volume Weighted Average Price, accumulated within each session.

        VWAP is only meaningful relative to a session start. `session` supplies the
        grouping key (normally the trading date); without it the accumulation would
        run across the entire series and the result would not be a VWAP at all.
        """
        typical_price = (high + low + close) / 3
        pv = typical_price * volume

        if session is None:
            index = close.index
            if isinstance(index, pd.DatetimeIndex):
                session = pd.Series(index.normalize(), index=index)
            else:
                # Non-datetime index carries no session boundary, so a single
                # cumulative window is the only defined answer.
                return pv.cumsum() / volume.cumsum()

        return pv.groupby(session).cumsum() / volume.groupby(session).cumsum()

    @staticmethod
    def bollinger_bands(series: pd.Series, period: int = 20, std_dev: int = 2):
        """Bollinger Bands"""
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, lower

    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        """Moving Average Convergence Divergence"""
        exp1 = series.ewm(span=fast, adjust=False).mean()
        exp2 = series.ewm(span=slow, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """Applies all core indicators to the dataframe"""
        df = df.copy()
        # Ensure required columns exist
        required = ['close', 'high', 'low', 'volume']
        if not all(col in df.columns for col in required):
            raise ValueError(f"DataFrame must contain {required}")

        df['rsi_14'] = Indicators.rsi(df['close'])
        df['sma_50'] = Indicators.sma(df['close'], 50)
        df['sma_200'] = Indicators.sma(df['close'], 200)
        df['ema_9'] = Indicators.ema(df['close'], 9)
        df['atr_14'] = Indicators.atr(df['high'], df['low'], df['close'])
        session = None
        if 'timestamp' in df.columns:
            session = pd.to_datetime(df['timestamp']).dt.normalize()
        df['vwap'] = Indicators.vwap(df['high'], df['low'], df['close'], df['volume'], session)
        
        upper, lower = Indicators.bollinger_bands(df['close'])
        df['bb_upper'] = upper
        df['bb_lower'] = lower
        
        macd, signal, hist = Indicators.macd(df['close'])
        df['macd_line'] = macd
        df['macd_signal'] = signal
        df['macd_hist'] = hist
        
        return df


class SupportResistance:
    @staticmethod
    def identify_levels(df: pd.DataFrame, window: int = 5, threshold: float = 0.02) -> List[float]:
        """
        Identifies support and resistance levels based on local swing highs and lows.
        Returns a consolidated list of price levels.
        """
        highs = df['high']
        lows = df['low']
        
        levels = []
        
        # Find local maxima and minima
        for i in range(window, len(df) - window):
            is_high = all(highs[i] > highs[i-j] for j in range(1, window+1)) and \
                      all(highs[i] > highs[i+j] for j in range(1, window+1))
            
            is_low = all(lows[i] < lows[i-j] for j in range(1, window+1)) and \
                     all(lows[i] < lows[i+j] for j in range(1, window+1))
            
            if is_high:
                levels.append(highs[i])
            if is_low:
                levels.append(lows[i])
                
        return SupportResistance.consolidate_levels(levels, threshold)

    @staticmethod
    def consolidate_levels(levels: List[float], threshold: float = 0.02) -> List[float]:
        """
        Clusters nearby levels to avoid duplicates.
        Threshold is a percentage (e.g., 0.02 = 2%).
        """
        if not levels:
            return []
            
        levels.sort()
        consolidated = []
        
        current_group = [levels[0]]
        
        for i in range(1, len(levels)):
            if levels[i] <= current_group[-1] * (1 + threshold):
                current_group.append(levels[i])
            else:
                consolidated.append(sum(current_group) / len(current_group))
                current_group = [levels[i]]
                
        consolidated.append(sum(current_group) / len(current_group))
        return consolidated

    @staticmethod
    def get_nearest_levels(price: float, levels: List[float]) -> Tuple[float, float]:
        """Returns the nearest support (below) and resistance (above) levels."""
        supports = [l for l in levels if l < price]
        resistances = [l for l in levels if l > price]
        
        nearest_support = max(supports) if supports else None
        nearest_resistance = min(resistances) if resistances else None
        
        return nearest_support, nearest_resistance


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
