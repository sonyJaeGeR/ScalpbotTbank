# risk_manager.py
import logging
from typing import Optional

import pandas as pd
import pandas_ta as ta

import config

class RiskManager:
    """
    Класс для управления рисками: расчет размера позиции,
    установка Stop Loss и Take Profit.
    """
    def __init__(self, tinkoff_client):
        self.tinkoff_client = tinkoff_client
        self.daily_trade_counts = {} # Словарь для отслеживания сделок {figi: count}

    def reset_daily_counts(self):
        """Сбрасывает счетчики дневных сделок."""
        self.daily_trade_counts = {}
        logging.info("Счетчики дневных сделок сброшены.")

    async def calculate_position_size(self, figi: str, last_price: float, candles_df: Optional[pd.DataFrame] = None):
        """
        Рассчитывает размер позиции в лотах, исходя из риска на сделку.
        Возвращает количество лотов для покупки/продажи.
        """
        # Проверка лимита сделок
        if self.daily_trade_counts.get(figi, 0) >= config.MAX_TRADES_PER_INSTRUMENT_PER_DAY:
            logging.warning(f"Достигнут дневной лимит сделок для {figi}")
            return 0

        try:
            account_balance = await self.tinkoff_client.get_account_balance()
            if account_balance <= 0:
                logging.error("Баланс счета равен нулю или отрицателен.")
                return 0
                
            if risk_amount <= 0:
                logging.error("Невозможно рассчитать риск: некорректный размер депозита или доля риска.")
                return 0

            # Получаем информацию о лотности инструмента
            instrument_info = await self.tinkoff_client.get_instrument_info(figi)
            if not instrument_info:
                return 0

            lot_size = instrument_info['lot']
            
            # Стоимость одного лота
            lot_cost = last_price * lot_size
            if lot_cost == 0:
                return 0

            per_share_risk = last_price * max(config.STOP_LOSS_PERCENT, config.MIN_STOP_LOSS_PERCENT)

            atr_risk = self._calculate_volatility_risk(candles_df)
            if atr_risk is not None:
                per_share_risk = max(per_share_risk, atr_risk)

            if per_share_risk <= 0:
                logging.warning(f"Пер-юнит риск для {figi} некорректен: {per_share_risk}")
                return 0

            # Максимальное количество лотов, которое мы можем себе позволить
            position_size_by_risk = int(risk_amount / (per_share_risk * lot_size))

            if position_size_by_risk <= 0:
                logging.warning(f"Размер позиции для {figi} равен 0. Недостаточно средств для риска.")
                return 0

            max_position_value = account_balance * config.MAX_POSITION_SHARE_PER_INSTRUMENT
            if max_position_value <= 0:
                logging.warning("Максимальный размер позиции не задан или равен 0.")
                return 0

            position_size_by_capital = int(max_position_value / lot_cost)

            position_size_in_lots = min(position_size_by_risk, position_size_by_capital)

            if position_size_in_lots == 0:
                logging.warning(f"Размер позиции для {figi} равен 0. Ограничения по риску или капиталу.")
                return 0

            return position_size_in_lots

        except Exception as e:
            logging.error(f"Ошибка при расчете размера позиции для {figi}: {e}")
            return 0

    def _calculate_volatility_risk(self, candles_df: Optional[pd.DataFrame]) -> Optional[float]:
        """Возвращает волатильностную компоненту риска на акцию на основе ATR."""
        if candles_df is None or candles_df.empty:
            return None

        required_columns = {'high', 'low', 'close'}
        if not required_columns.issubset(candles_df.columns):
            return None

        if len(candles_df) < config.ATR_PERIOD:
            return None

        try:
            atr_series = ta.atr(
                high=candles_df['high'],
                low=candles_df['low'],
                close=candles_df['close'],
                length=config.ATR_PERIOD,
            )
            if atr_series is None or atr_series.empty:
                return None

            atr_value = atr_series.iloc[-1]
            if pd.isna(atr_value) or atr_value <= 0:
                return None

            return float(atr_value) * config.ATR_STOP_MULTIPLIER
        except Exception as error:
            logging.error(f"Не удалось рассчитать ATR для оценки риска: {error}")
            return None

    def calculate_sl_tp(self, entry_price: float, direction: str, candles_df: Optional[pd.DataFrame] = None):
        """
        Рассчитывает уровни Stop Loss и Take Profit.
        :param entry_price: Цена входа в позицию.
        :param direction: 'BUY' или 'SELL'.
        :return: (stop_loss_price, take_profit_price)
        """
        base_stop_distance = entry_price * max(config.STOP_LOSS_PERCENT, config.MIN_STOP_LOSS_PERCENT)
        atr_risk = self._calculate_volatility_risk(candles_df)
        if atr_risk is not None:
            base_stop_distance = max(base_stop_distance, atr_risk)

        take_profit_distance = base_stop_distance * config.TAKE_PROFIT_RATIO

        if direction == "BUY":
            stop_loss_price = entry_price - base_stop_distance
            take_profit_price = entry_price + take_profit_distance
        elif direction == "SELL":
            stop_loss_price = entry_price + base_stop_distance
            take_profit_price = entry_price - take_profit_distance
        else:
            return None, None

        stop_loss_price = max(stop_loss_price, 0.0)
        take_profit_price = max(take_profit_price, 0.0)

        return stop_loss_price, take_profit_price
        
    def record_trade(self, figi: str):
        """Увеличивает счетчик сделок для инструмента."""
        self.daily_trade_counts[figi] = self.daily_trade_counts.get(figi, 0) + 1
        logging.info(f"Сделка для {figi} записана. Всего сделок сегодня: {self.daily_trade_counts[figi]}")
