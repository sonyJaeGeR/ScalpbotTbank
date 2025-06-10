# strategy.py
import pandas as pd
import pandas_ta as ta
import logging

import config

class StrategyManager:
    """
    Управляет выбором и применением стратегий в зависимости от рыночных условий.
    """
    def __init__(self):
        pass

    def get_market_regime(self, candles_df: pd.DataFrame):
        """
        Определяет режим рынка (тренд или боковик) с помощью индикатора ADX.
        """
        if candles_df is None or candles_df.empty:
            return "UNKNOWN"
            
        try:
            # Расчет ADX с помощью pandas-ta
            adx_data = candles_df.ta.adx()
            if adx_data is None or adx_data.empty:
                return "UNKNOWN"
            
            last_adx = adx_data.iloc[-1]['ADX_14']
            
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
        regime = self.get_market_regime(candles_df)

        if regime == "TREND":
            return self._ma_crossover_signal(candles_df)
        elif regime == "RANGE":
            return self._bb_rsi_signal(candles_df, last_price)
        else:
            return "HOLD", "Режим рынка не определен"

    def _ma_crossover_signal(self, candles_df: pd.DataFrame):
        """
        Стратегия пересечения скользящих средних.
        Сигнал на покупку: быстрая MA пересекает медленную снизу вверх.
        Сигнал на продажу: быстрая MA пересекает медленную сверху вниз.
        """
        try:
            candles_df.ta.sma(length=config.MA_FAST_PERIOD, append=True)
            candles_df.ta.sma(length=config.MA_SLOW_PERIOD, append=True)
            
            fast_ma_col = f"SMA_{config.MA_FAST_PERIOD}"
            slow_ma_col = f"SMA_{config.MA_SLOW_PERIOD}"

            last_row = candles_df.iloc[-1]
            prev_row = candles_df.iloc[-2]

            # Проверка пересечения
            if prev_row[fast_ma_col] < prev_row[slow_ma_col] and last_row[fast_ma_col] > last_row[slow_ma_col]:
                return "BUY", f"Пересечение MA ({config.MA_FAST_PERIOD}/{config.MA_SLOW_PERIOD}) вверх"
            
            if prev_row[fast_ma_col] > prev_row[slow_ma_col] and last_row[fast_ma_col] < last_row[slow_ma_col]:
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
            candles_df.ta.bbands(length=config.BB_PERIOD, std=config.BB_STD_DEV, append=True)
            candles_df.ta.rsi(length=config.RSI_PERIOD, append=True)
            
            lower_band_col = f"BBL_{config.BB_PERIOD}_{config.BB_STD_DEV}.0"
            upper_band_col = f"BBU_{config.BB_PERIOD}_{config.BB_STD_DEV}.0"
            rsi_col = f"RSI_{config.RSI_PERIOD}"
            
            last_row = candles_df.iloc[-1]
            
            lower_band = last_row[lower_band_col]
            upper_band = last_row[upper_band_col]
            rsi = last_row[rsi_col]

            # Проверка сигналов
            if last_price < lower_band and rsi < config.RSI_OVERSOLD:
                return "BUY", f"Цена ({last_price}) ниже BB ({lower_band:.2f}) и RSI ({rsi:.2f}) < {config.RSI_OVERSOLD}"
            
            if last_price > upper_band and rsi > config.RSI_OVERBOUGHT:
                return "SELL", f"Цена ({last_price}) выше BB ({upper_band:.2f}) и RSI ({rsi:.2f}) > {config.RSI_OVERBOUGHT}"

            return "HOLD", "Нет сигнала по BB+RSI"
        except Exception as e:
            logging.error(f"Ошибка в стратегии BB+RSI: {e}")
            return "HOLD", "Ошибка расчета BB+RSI"
