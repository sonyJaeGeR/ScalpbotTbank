# risk_manager.py
import logging
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

    async def calculate_position_size(self, figi: str, last_price: float):
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
                
            risk_amount = account_balance * config.RISK_PER_TRADE
            
            # Получаем информацию о лотности инструмента
            instrument_info = await self.tinkoff_client.get_instrument_info(figi)
            if not instrument_info:
                return 0
            
            lot_size = instrument_info['lot']
            
            # Стоимость одного лота
            lot_cost = last_price * lot_size
            if lot_cost == 0:
                return 0

            # Максимальное количество лотов, которое мы можем себе позволить
            position_size_in_lots = int(risk_amount / (lot_cost * config.STOP_LOSS_PERCENT))
            
            if position_size_in_lots == 0:
                logging.warning(f"Размер позиции для {figi} равен 0. Недостаточно средств для риска.")
                return 0

            return position_size_in_lots

        except Exception as e:
            logging.error(f"Ошибка при расчете размера позиции для {figi}: {e}")
            return 0

    def calculate_sl_tp(self, entry_price: float, direction: str):
        """
        Рассчитывает уровни Stop Loss и Take Profit.
        :param entry_price: Цена входа в позицию.
        :param direction: 'BUY' или 'SELL'.
        :return: (stop_loss_price, take_profit_price)
        """
        if direction == "BUY":
            stop_loss_price = entry_price * (1 - config.STOP_LOSS_PERCENT)
            take_profit_price = entry_price * (1 + config.STOP_LOSS_PERCENT * config.TAKE_PROFIT_RATIO)
        elif direction == "SELL":
            stop_loss_price = entry_price * (1 + config.STOP_LOSS_PERCENT)
            take_profit_price = entry_price * (1 - config.STOP_LOSS_PERCENT * config.TAKE_PROFIT_RATIO)
        else:
            return None, None
            
        return stop_loss_price, take_profit_price
        
    def record_trade(self, figi: str):
        """Увеличивает счетчик сделок для инструмента."""
        self.daily_trade_counts[figi] = self.daily_trade_counts.get(figi, 0) + 1
        logging.info(f"Сделка для {figi} записана. Всего сделок сегодня: {self.daily_trade_counts[figi]}")
