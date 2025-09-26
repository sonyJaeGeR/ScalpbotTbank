# tinkoff_client.py
import asyncio
from datetime import datetime, timedelta
import logging

from tinkoff.invest import (
    AsyncClient,
    CandleInterval,
    InstrumentIdType,
    OrderDirection,
    OrderType,
    StopOrderDirection,
    StopOrderExpirationType,
    StopOrderType,
)
from tinkoff.invest.utils import now, quotation_to_decimal

import config

class TinkoffClient:
    """
    Класс-обертка для работы с Tinkoff Invest API.
    Инкапсулирует логику подключения, получения данных и отправки ордеров.
    """
    def __init__(self, token: str, use_sandbox: bool):
        self.token = token
        self.use_sandbox = use_sandbox
        self.client = None
        # Словарь для кэширования информации об инструментах (лот, мин. шаг цены)
        self.instrument_info_cache = {}

    async def __aenter__(self):
        """Асинхронный вход в контекстный менеджер для установки соединения."""
        for attempt in range(config.API_RETRY_COUNT):
            try:
                if self.use_sandbox:
                    # Подключение к "песочнице"
                    self.client = await AsyncClient(self.token, use_sandbox=True).__aenter__()
                else:
                    # Подключение к реальному счету
                    self.client = await AsyncClient(self.token).__aenter__()
                logging.info("Успешное подключение к Tinkoff Invest API.")
                return self
            except Exception as e:
                logging.error(f"Ошибка подключения к API (попытка {attempt + 1}): {e}")
                if attempt < config.API_RETRY_COUNT - 1:
                    await asyncio.sleep(config.API_RETRY_DELAY_SECONDS)
                else:
                    raise  # Перебрасываем исключение после последней попытки

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Асинхронный выход из контекстного менеджера для закрытия соединения."""
        if self.client:
            await self.client.__aexit__(exc_type, exc_val, exc_tb)
            logging.info("Соединение с Tinkoff Invest API закрыто.")

    async def get_all_tradable_shares(self):
        """Получает список всех торгуемых акций на Московской бирже."""
        try:
            instruments = await self.client.instruments.shares()
            # Фильтруем акции, доступные для торговли и торгуемые за рубли
            tradable_shares = [
                share for share in instruments.instruments
                if share.exchange == "MOEX" and share.currency == "rub" and share.buy_available_flag and share.sell_available_flag
            ]
            logging.info(f"Найдено {len(tradable_shares)} торгуемых акций.")
            return tradable_shares
        except Exception as e:
            logging.error(f"Ошибка при получении списка акций: {e}")
            return []

    async def get_historical_candles(self, figi: str, days: int, interval: CandleInterval = CandleInterval.CANDLE_INTERVAL_5_MINUTE):
        """Получает исторические свечи для инструмента за указанное количество дней."""
        try:
            candles = []
            async for candle in self.client.get_all_candles(
                figi=figi,
                from_=now() - timedelta(days=days),
                interval=interval,
            ):
                candles.append(candle)
            return candles
        except Exception as e:
            logging.error(f"Ошибка при получении свечей для FIGI {figi}: {e}")
            return []
            
    async def get_last_prices(self, figi_list: list):
        """Получает последние цены для списка инструментов."""
        try:
            response = await self.client.market_data.get_last_prices(figi=figi_list)
            return {price.figi: quotation_to_decimal(price.price) for price in response.last_prices}
        except Exception as e:
            logging.error(f"Ошибка при получении последних цен: {e}")
            return {}

    async def get_instrument_info(self, figi: str):
        """Получает и кэширует информацию об инструменте (лот, шаг цены)."""
        if figi in self.instrument_info_cache:
            return self.instrument_info_cache[figi]
        
        try:
            response = await self.client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi,
            )
            instrument = response.instrument
            info = {
                'lot': instrument.lot,
                'min_price_increment': quotation_to_decimal(instrument.min_price_increment)
            }
            self.instrument_info_cache[figi] = info
            return info
        except Exception as e:
            logging.error(f"Ошибка при получении информации об инструменте {figi}: {e}")
            return None

    async def get_account_balance(self):
        """Получает общий баланс счета в рублях."""
        try:
            if self.use_sandbox:
                # В песочнице API для портфеля не всегда работает корректно,
                # можно использовать API для открытия счета с начальным балансом
                await self.client.sandbox.open_sandbox_account() # Убедимся, что счет есть
                portfolio = await self.client.sandbox.get_sandbox_portfolio(account_id=config.TINKOFF_ACCOUNT_ID)
            else:
                portfolio = await self.client.operations.get_portfolio(account_id=config.TINKOFF_ACCOUNT_ID)
            
            total_value = quotation_to_decimal(portfolio.total_amount_portfolio)
            return total_value
        except Exception as e:
            logging.error(f"Ошибка при получении баланса счета: {e}")
            # Возвращаем дефолтное значение для продолжения работы
            return 100000.0 

    async def post_market_order(self, figi: str, quantity: int, direction: OrderDirection):
        """Размещает рыночную заявку."""
        try:
            order_id = str(datetime.utcnow().timestamp())  # Уникальный ID заявки
            if self.use_sandbox:
                response = await self.client.sandbox.post_sandbox_order(
                    account_id=config.TINKOFF_ACCOUNT_ID,
                    figi=figi,
                    quantity=quantity,
                    direction=direction,
                    order_type=OrderType.ORDER_TYPE_MARKET,
                    order_id=order_id,
                )
            else:
                response = await self.client.orders.post_order(
                    account_id=config.TINKOFF_ACCOUNT_ID,
                    figi=figi,
                    quantity=quantity,
                    direction=direction,
                    order_type=OrderType.ORDER_TYPE_MARKET,
                    order_id=order_id,
                )
            logging.info(f"Размещена рыночная заявка: {response}")
            return response
        except Exception as e:
            logging.error(f"Ошибка при размещении рыночной заявки для {figi}: {e}")
            return None
    async def post_stop_order(
        self,
        figi: str,
        quantity: int,
        stop_price: float,
        direction: StopOrderDirection,
        stop_order_type: StopOrderType,
    ):
        """Размещает стоп-заявку (Stop-Loss или Take-Profit)."""
        try:
            from tinkoff.invest.utils import decimal_to_quotation
            
            price_increment_info = await self.get_instrument_info(figi)
            if not price_increment_info:
                return None

            min_price_increment = price_increment_info['min_price_increment']
            
            # Округляем цену до шага цены инструмента
            stop_price = round(stop_price / float(min_price_increment)) * float(min_price_increment)
            
            
            price_quotation = decimal_to_quotation(stop_price)
            
            if self.use_sandbox:
                response = await self.client.sandbox.post_sandbox_stop_order(
                    account_id=config.TINKOFF_ACCOUNT_ID,
                    figi=figi,
                    quantity=quantity,
                    price=price_quotation,
                    stop_price=price_quotation,
                    direction=direction,
                    stop_order_type=stop_order_type,
                    expiration_type=StopOrderExpirationType.STOP_ORDER_EXPIRATION_TYPE_GTC,
                )
            else:
                response = await self.client.stop_orders.post_stop_order(
                    account_id=config.TINKOFF_ACCOUNT_ID,
                    figi=figi,
                    quantity=quantity,
                    price=price_quotation,
                    stop_price=price_quotation,
                    direction=direction,
                    stop_order_type=stop_order_type,
                    expiration_type=StopOrderExpirationType.STOP_ORDER_EXPIRATION_TYPE_GTC,
                )
            
            logging.info(f"Размещена стоп-заявка: {response}")
            return response
        except Exception as e:
            logging.error(f"Ошибка размещения стоп-заявки для {figi} по цене {stop_price}: {e}")
            return None
