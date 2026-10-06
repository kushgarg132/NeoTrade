import pandas as pd
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

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
