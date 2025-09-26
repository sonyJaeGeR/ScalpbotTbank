# strategy.py
import logging
from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta


import config

class StrategyManager:
    """
    Управляет выбором и применением стратегий в зависимости от рыночных условий.
    """
    def __init__(self):
        self.min_candles_required = config.MIN_CANDLES_FOR_SIGNAL

    def get_market_regime(self, candles_df: pd.DataFrame):
        """
        Определяет режим рынка (тренд или боковик) с помощью индикатора ADX.
        """
        if candles_df is None or candles_df.empty:
            return "UNKNOWN"

        try:
            if len(candles_df) < config.ADX_PERIOD + 1:
                return "UNKNOWN"

            # Расчет ADX с помощью pandas-ta
            adx_data = ta.adx(
                high=candles_df['high'],
                low=candles_df['low'],
                close=candles_df['close'],
                length=config.ADX_PERIOD,
            )
            if adx_data is None or adx_data.empty:
                return "UNKNOWN"

            adx_column = f"ADX_{config.ADX_PERIOD}"
            if adx_column not in adx_data.columns:
                return "UNKNOWN"

            last_adx = adx_data.iloc[-1][adx_column]

            if last_adx > config.ADX_TREND_THRESHOLD:
                logging.debug(f"Режим рынка: ТРЕНД (ADX={last_adx:.2f})")
                return "TREND"
            else:
                logging.debug(f"Режим рынка: БОКОВИК (ADX={last_adx:.2f})")
                return "RANGE"
        except Exception as e:
            logging.error(f"Ошибка при расчете ADX: {e}")
            return "UNKNOWN"

    def get_signal(self, candles_df: pd.DataFrame, last_price: float):
        """
        Возвращает торговый сигнал на основе текущего режима рынка.
        """
        prepared_df = self._prepare_dataframe(candles_df)

        if prepared_df is None or len(prepared_df) < self.min_candles_required:
            return "HOLD", "Недостаточно данных для анализа"

        regime = self.get_market_regime(prepared_df)

        if regime == "TREND":
            signal, reason = self._ma_crossover_signal(prepared_df)
        elif regime == "RANGE":
            signal, reason = self._bb_rsi_signal(prepared_df, last_price)
        else:
            return "HOLD", "Режим рынка не определен"

        if signal in {"BUY", "SELL"}:
            volume_confirmed, volume_reason = self._volume_confirmation(prepared_df)
            if not volume_confirmed:
                return "HOLD", f"Сигнал отклонен фильтром по объему ({volume_reason})"

        return signal, reason

    def _ma_crossover_signal(self, candles_df: pd.DataFrame):
        """
        Стратегия пересечения скользящих средних.
        Сигнал на покупку: быстрая MA пересекает медленную снизу вверх.
        Сигнал на продажу: быстрая MA пересекает медленную сверху вниз.
        """
        try:
            if len(candles_df) < config.MA_SLOW_PERIOD + 2:
                return "HOLD", "Недостаточно данных для MA"

            fast_ma_series = ta.sma(candles_df['close'], length=config.MA_FAST_PERIOD)
            slow_ma_series = ta.sma(candles_df['close'], length=config.MA_SLOW_PERIOD)

            if fast_ma_series is None or slow_ma_series is None:
                return "HOLD", "Не удалось рассчитать MA"

            last_fast = fast_ma_series.iloc[-1]
            last_slow = slow_ma_series.iloc[-1]
            prev_fast = fast_ma_series.iloc[-2]
            prev_slow = slow_ma_series.iloc[-2]

            if pd.isna(last_fast) or pd.isna(last_slow) or pd.isna(prev_fast) or pd.isna(prev_slow):
                return "HOLD", "MA содержат пропуски"

            # Проверка пересечения
            if prev_fast < prev_slow and last_fast > last_slow:
                return "BUY", f"Пересечение MA ({config.MA_FAST_PERIOD}/{config.MA_SLOW_PERIOD}) вверх"

            if prev_fast > prev_slow and last_fast < last_slow:
                return "SELL", f"Пересечение MA ({config.MA_FAST_PERIOD}/{config.MA_SLOW_PERIOD}) вниз"

            return "HOLD", "Нет пересечения MA"
        except Exception as e:
            logging.error(f"Ошибка в стратегии MA Crossover: {e}")
            return "HOLD", "Ошибка расчета MA"

    def _bb_rsi_signal(self, candles_df: pd.DataFrame, last_price: float):
        """
        Стратегия Ленты Боллинджера + RSI.
        Покупка: цена ниже нижней ленты И RSI в зоне перепроданности.
        Продажа: цена выше верхней ленты И RSI в зоне перекупленности.
        """
        try:
            # Расчет индикаторов
            if len(candles_df) < config.BB_PERIOD + config.RSI_PERIOD:
                return "HOLD", "Недостаточно данных для BB+RSI"

            bb_data = ta.bbands(candles_df['close'], length=config.BB_PERIOD, std=config.BB_STD_DEV)
            rsi_series = ta.rsi(candles_df['close'], length=config.RSI_PERIOD)

            if bb_data is None or rsi_series is None:
                return "HOLD", "Не удалось рассчитать BB или RSI"

            lower_band_col = f"BBL_{config.BB_PERIOD}_{config.BB_STD_DEV}.0"
            upper_band_col = f"BBU_{config.BB_PERIOD}_{config.BB_STD_DEV}.0"
            if lower_band_col not in bb_data.columns or upper_band_col not in bb_data.columns:
                return "HOLD", "Ленты Боллинджера не содержат нужных колонок"

            lower_band = bb_data.iloc[-1][lower_band_col]
            upper_band = bb_data.iloc[-1][upper_band_col]
            rsi = rsi_series.iloc[-1]

            if pd.isna(lower_band) or pd.isna(upper_band) or pd.isna(rsi):
                return "HOLD", "BB или RSI содержат пропуски"

            # Проверка сигналов
            if last_price < lower_band and rsi < config.RSI_OVERSOLD:
                return "BUY", f"Цена ({last_price:.2f}) ниже BB ({lower_band:.2f}) и RSI ({rsi:.2f}) < {config.RSI_OVERSOLD}"

            if last_price > upper_band and rsi > config.RSI_OVERBOUGHT:
                return "SELL", f"Цена ({last_price:.2f}) выше BB ({upper_band:.2f}) и RSI ({rsi:.2f}) > {config.RSI_OVERBOUGHT}"

            return "HOLD", "Нет сигнала по BB+RSI"
        except Exception as e:
            logging.error(f"Ошибка в стратегии BB+RSI: {e}")
            return "HOLD", "Ошибка расчета BB+RSI"

    def _prepare_dataframe(self, candles_df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Приводит DataFrame свечей к упорядоченному и числовому виду."""
        if candles_df is None or candles_df.empty:
            return None

        df = candles_df.copy()
        df = df.sort_index()

        columns_to_numeric = [col for col in ['open', 'high', 'low', 'close', 'volume'] if col in df.columns]
        for column in columns_to_numeric:
            df[column] = pd.to_numeric(df[column], errors='coerce')

        df.dropna(subset=['high', 'low', 'close'], inplace=True)

        return df if not df.empty else None

    def _volume_confirmation(self, candles_df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
        """Проверяет, подтверждается ли сигнал всплеском объема."""
        if 'volume' not in candles_df.columns or candles_df['volume'].isna().all():
            return True, None

        window = min(config.VOLUME_CONFIRMATION_WINDOW, len(candles_df))
        if window < 3:
            return True, None

        recent_volumes = candles_df['volume'].tail(window)
        if recent_volumes[:-1].mean() == 0:
            return True, None

        last_volume = recent_volumes.iloc[-1]
        avg_volume = recent_volumes[:-1].mean()

        if avg_volume == 0:
            return True, None

        is_confirmed = last_volume >= avg_volume * config.VOLUME_SPIKE_FACTOR
        reason = f"объем {last_volume:.0f} < требуемого {avg_volume * config.VOLUME_SPIKE_FACTOR:.0f}"
        return is_confirmed, None if is_confirmed else reason
