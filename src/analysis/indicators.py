import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator, SMAIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import VolumeWeightedAveragePrice, OnBalanceVolumeIndicator


class TechnicalIndicators:
    """Collection of technical analysis indicators."""

    @staticmethod
    def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical indicators to a DataFrame."""
        df = df.copy()

        df = TechnicalIndicators.add_rsi(df)
        df = TechnicalIndicators.add_macd(df)
        df = TechnicalIndicators.add_bollinger_bands(df)
        df = TechnicalIndicators.add_atr(df)
        df = TechnicalIndicators.add_ema(df, periods=[9, 21, 50, 200])
        df = TechnicalIndicators.add_sma(df, periods=[20, 50, 200])
        df = TechnicalIndicators.add_adx(df)
        df = TechnicalIndicators.add_stochastic(df)
        df = TechnicalIndicators.add_obv(df)
        df = TechnicalIndicators.add_vwap(df)

        return df

    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add RSI indicator."""
        rsi = RSIIndicator(close=df["close"], window=period)
        df[f"rsi_{period}"] = rsi.rsi()
        return df

    @staticmethod
    def add_macd(
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> pd.DataFrame:
        """Add MACD indicators."""
        macd = MACD(
            close=df["close"],
            window_slow=slow,
            window_fast=fast,
            window_sign=signal
        )
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_histogram"] = macd.macd_diff()
        return df

    @staticmethod
    def add_bollinger_bands(
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0
    ) -> pd.DataFrame:
        """Add Bollinger Bands."""
        bb = BollingerBands(
            close=df["close"],
            window=period,
            window_dev=std_dev
        )
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_middle"] = bb.bollinger_mavg()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_width"] = bb.bollinger_wband()
        df["bb_pct"] = bb.bollinger_pband()
        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add Average True Range."""
        atr = AverageTrueRange(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=period
        )
        df[f"atr_{period}"] = atr.average_true_range()
        return df

    @staticmethod
    def add_ema(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
        """Add Exponential Moving Averages."""
        if periods is None:
            periods = [9, 21, 50, 200]

        for period in periods:
            ema = EMAIndicator(close=df["close"], window=period)
            df[f"ema_{period}"] = ema.ema_indicator()

        return df

    @staticmethod
    def add_sma(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
        """Add Simple Moving Averages."""
        if periods is None:
            periods = [20, 50, 200]

        for period in periods:
            sma = SMAIndicator(close=df["close"], window=period)
            df[f"sma_{period}"] = sma.sma_indicator()

        return df

    @staticmethod
    def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add Average Directional Index."""
        adx = ADXIndicator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=period
        )
        df["adx"] = adx.adx()
        df["adx_pos"] = adx.adx_pos()
        df["adx_neg"] = adx.adx_neg()
        return df

    @staticmethod
    def add_stochastic(
        df: pd.DataFrame,
        k_period: int = 14,
        d_period: int = 3
    ) -> pd.DataFrame:
        """Add Stochastic Oscillator."""
        stoch = StochasticOscillator(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            window=k_period,
            smooth_window=d_period
        )
        df["stoch_k"] = stoch.stoch()
        df["stoch_d"] = stoch.stoch_signal()
        return df

    @staticmethod
    def add_obv(df: pd.DataFrame) -> pd.DataFrame:
        """Add On-Balance Volume."""
        obv = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"])
        df["obv"] = obv.on_balance_volume()
        return df

    @staticmethod
    def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """Add Volume Weighted Average Price."""
        vwap = VolumeWeightedAveragePrice(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"]
        )
        df["vwap"] = vwap.volume_weighted_average_price()
        return df

    @staticmethod
    def calculate_returns(df: pd.DataFrame, periods: list[int] = None) -> pd.DataFrame:
        """Calculate price returns over various periods."""
        if periods is None:
            periods = [1, 5, 10, 20]

        for period in periods:
            df[f"return_{period}"] = df["close"].pct_change(periods=period)

        return df

    @staticmethod
    def calculate_volatility(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """Calculate rolling volatility."""
        df[f"volatility_{period}"] = df["close"].pct_change().rolling(window=period).std() * np.sqrt(252)
        return df

    @staticmethod
    def detect_crossover(
        series1: pd.Series,
        series2: pd.Series
    ) -> pd.Series:
        """
        Detect crossovers between two series.

        Returns:
            1 for bullish crossover (series1 crosses above series2)
            -1 for bearish crossover (series1 crosses below series2)
            0 for no crossover
        """
        prev_diff = series1.shift(1) - series2.shift(1)
        curr_diff = series1 - series2

        bullish = (prev_diff < 0) & (curr_diff > 0)
        bearish = (prev_diff > 0) & (curr_diff < 0)

        crossover = pd.Series(0, index=series1.index)
        crossover[bullish] = 1
        crossover[bearish] = -1

        return crossover

    @staticmethod
    def is_golden_cross(df: pd.DataFrame, short_period: int = 50, long_period: int = 200) -> bool:
        """Check if golden cross occurred (short MA crosses above long MA)."""
        if f"sma_{short_period}" not in df.columns:
            df = TechnicalIndicators.add_sma(df, [short_period, long_period])

        short_ma = df[f"sma_{short_period}"]
        long_ma = df[f"sma_{long_period}"]

        crossover = TechnicalIndicators.detect_crossover(short_ma, long_ma)
        return crossover.iloc[-1] == 1

    @staticmethod
    def is_death_cross(df: pd.DataFrame, short_period: int = 50, long_period: int = 200) -> bool:
        """Check if death cross occurred (short MA crosses below long MA)."""
        if f"sma_{short_period}" not in df.columns:
            df = TechnicalIndicators.add_sma(df, [short_period, long_period])

        short_ma = df[f"sma_{short_period}"]
        long_ma = df[f"sma_{long_period}"]

        crossover = TechnicalIndicators.detect_crossover(short_ma, long_ma)
        return crossover.iloc[-1] == -1

    @staticmethod
    def get_trend(df: pd.DataFrame, period: int = 20) -> str:
        """
        Determine the current trend.

        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        if len(df) < period + 5:
            return "neutral"

        sma = df["close"].rolling(window=period).mean()
        current_price = df["close"].iloc[-1]
        current_sma = sma.iloc[-1]
        prev_sma = sma.iloc[-5]

        if current_price > current_sma and current_sma > prev_sma:
            return "bullish"
        elif current_price < current_sma and current_sma < prev_sma:
            return "bearish"
        return "neutral"

    @staticmethod
    def get_support_resistance(
        df: pd.DataFrame,
        lookback: int = 20,
        num_levels: int = 3
    ) -> dict:
        """
        Calculate simple support and resistance levels.

        Returns:
            Dict with 'support' and 'resistance' lists
        """
        recent_data = df.tail(lookback)

        highs = recent_data["high"].nlargest(num_levels).values
        lows = recent_data["low"].nsmallest(num_levels).values

        return {
            "resistance": sorted(highs, reverse=True),
            "support": sorted(lows)
        }
