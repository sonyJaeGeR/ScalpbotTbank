# main.py
import asyncio
import logging
import threading
import time
from datetime import datetime

import pandas as pd
import pandas_ta as ta
import schedule
from tinkoff.invest import CandleInterval, OrderDirection, StopOrderDirection

import config
from risk_manager import RiskManager
from strategy import StrategyManager
from telegram_bot import TelegramBot
from tinkoff_client import TinkoffClient

# --- Глобальные переменные состояния ---
trading_active = False
top_instruments = []
last_prices = {}
daily_report = {"trades": 0, "profit": 0, "loss": 0}

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Функции управления роботом (для Telegram) ---
def start_trading():
    global trading_active
    if not trading_active:
        trading_active = True
        logging.info("Торговля активирована через Telegram.")

def stop_trading():
    global trading_active
    if trading_active:
        trading_active = False
        logging.info("Торговля деактивирована через Telegram.")
        
def get_status():
    """Возвращает текущий статус робота."""
    status_text = f"🤖 **Статус робота** 🤖\n\n"
    status_text += f"Состояние: {'АКТИВЕН' if trading_active else 'ОСТАНОВЛЕН'}\n"
    status_text += f"Режим API: {'Песочница' if config.USE_SANDBOX else 'Боевой'}\n\n"
    status_text += f"**Торгуемые инструменты ({len(top_instruments)}):**\n"
    for inst in top_instruments:
        price = last_prices.get(inst['figi'], 'N/A')
        status_text += f"- {inst['ticker']} ({inst['name']}): {price} RUB\n"
    return status_text

# --- Основные функции робота ---
async def select_top_volatile_instruments(client: TinkoffClient):
    """
    Выбирает топ-N самых волатильных инструментов на основе ATR.
    """
    global top_instruments, telegram_bot
    logging.info("Начинаем выбор самых волатильных инструментов...")
    await telegram_bot.send_message("🔍 Обновляю список волатильных инструментов...")
    
    all_shares = await client.get_all_tradable_shares()
    if not all_shares:
        await telegram_bot.send_message("⚠️ Не удалось получить список акций для анализа.")
        return

    volatility_data = []
    for share in all_shares:
        # Получаем дневные свечи для расчета ATR
        candles = await client.get_historical_candles(share.figi, days=config.VOLATILITY_PERIOD_DAYS, interval=CandleInterval.CANDLE_INTERVAL_DAY)
        if len(candles) < config.VOLATILITY_PERIOD_DAYS:
            continue
            
        df = pd.DataFrame([{
            'time': c.time,
            'high': float(c.high.units + c.high.nano / 1e9),
            'low': float(c.low.units + c.low.nano / 1e9),
            'close': float(c.close.units + c.close.nano / 1e9),
        } for c in candles])
        
        # Расчет ATR
        atr = df.ta.atr(length=14).iloc[-1]
        last_close = df['close'].iloc[-1]
        
        # Нормализуем ATR в процентах от цены закрытия
        if last_close > 0:
            normalized_atr = (atr / last_close) * 100
            volatility_data.append({'figi': share.figi, 'ticker': share.ticker, 'name': share.name, 'volatility': normalized_atr})

    if not volatility_data:
        await telegram_bot.send_message("⚠️ Не удалось рассчитать волатильность ни для одного инструмента.")
        return

    # Сортируем по убыванию волатильности и берем топ-N
    volatility_data.sort(key=lambda x: x['volatility'], reverse=True)
    top_instruments = volatility_data[:config.TOP_VOLATILE_INSTRUMENTS_COUNT]
    
    message = "✅ **Топ-10 волатильных инструментов на сегодня:**\n"
    for i, item in enumerate(top_instruments):
        message += f"{i+1}. {item['ticker']} ({item['name']}) - Волатильность: {item['volatility']:.2f}%\n"
    await telegram_bot.send_message(message)
    logging.info("Список волатильных инструментов обновлен.")

async def trading_cycle(client: TinkoffClient, risk_manager: RiskManager, strategy_manager: StrategyManager):
    """
    Основной торговый цикл, который выполняется непрерывно.
    """
    global top_instruments, last_prices, telegram_bot
    
    if not top_instruments:
        logging.warning("Список инструментов пуст. Пропускаем торговый цикл.")
        await asyncio.sleep(60)
        return

    figi_list = [inst['figi'] for inst in top_instruments]
    
    # 1. Получаем актуальные цены
    current_prices = await client.get_last_prices(figi_list)
    if not current_prices:
        logging.warning("Не удалось получить последние цены. Пропускаем итерацию.")
        return
    last_prices.update(current_prices)

    # 2. Проходим по каждому инструменту и ищем сигналы
    for instrument in top_instruments:
        figi = instrument['figi']
        last_price = current_prices.get(figi)

        if not last_price:
            continue
        
        # Получаем 5-минутные свечи для анализа
        candles = await client.get_historical_candles(figi, days=2, interval=CandleInterval.CANDLE_INTERVAL_5_MINUTE)
        if len(candles) < 50: # Нужно достаточно данных для индикаторов
            continue
        
        candles_df = pd.DataFrame([{
            'time': c.time, 'open': float(c.open.units + c.open.nano/1e9),
            'high': float(c.high.units + c.high.nano/1e9), 'low': float(c.low.units + c.low.nano/1e9),
            'close': float(c.close.units + c.close.nano/1e9), 'volume': c.volume
        } for c in candles])
        candles_df.set_index('time', inplace=True)
        
        # Получаем сигнал от менеджера стратегий
        signal, reason = strategy_manager.get_signal(candles_df, float(last_price))
        
        if signal != "HOLD":
            logging.info(f"Сигнал для {instrument['ticker']}: {signal}. Причина: {reason}")
            
            # Рассчитываем размер позиции
            position_size_lots = await risk_manager.calculate_position_size(figi, float(last_price))
            
            if position_size_lots > 0:
                instrument_info = await client.get_instrument_info(figi)
                quantity = position_size_lots * instrument_info['lot']
                direction = OrderDirection.ORDER_DIRECTION_BUY if signal == "BUY" else OrderDirection.ORDER_DIRECTION_SELL
                
                # Отправляем рыночный ордер
                order = await client.post_market_order(figi, position_size_lots, direction)
                
                if order:
                    risk_manager.record_trade(figi)
                    
                    # Расчет и установка SL/TP
                    sl_price, tp_price = risk_manager.calculate_sl_tp(float(last_price), signal)
                    
                    sl_direction = StopOrderDirection.STOP_ORDER_DIRECTION_SELL if signal == "BUY" else StopOrderDirection.STOP_ORDER_DIRECTION_BUY
                    tp_direction = sl_direction
                    
                    await client.post_stop_order(figi, quantity, sl_price, sl_direction)
                    await client.post_stop_order(figi, quantity, tp_price, tp_direction)
                    
                    # Уведомление в Telegram
                    trade_message = (
                        f"🚀 **НОВАЯ СДЕЛКА** 🚀\n\n"
                        f"Инструмент: {instrument['ticker']} ({instrument['name']})\n"
                        f"Направление: {'ПОКУПКА' if signal == 'BUY' else 'ПРОДАЖА'}\n"
                        f"Цена входа: {last_price:.4f} RUB\n"
                        f"Объем: {quantity} шт. ({position_size_lots} лотов)\n"
                        f"Stop Loss: {sl_price:.4f}\n"
                        f"Take Profit: {tp_price:.4f}\n\n"
                        f"<i>Причина: {reason}</i>"
                    )
                    await telegram_bot.send_message(trade_message)
            else:
                logging.info(f"Не удалось войти в сделку по {instrument['ticker']}: размер позиции 0 или лимит сделок.")
    
async def main():
    """Главная асинхронная функция."""
    global trading_active, telegram_bot
    
    # Инициализация всех компонентов
    risk_manager = None
    strategy_manager = StrategyManager()
    
    # Запускаем Telegram-бота в отдельном потоке
    app_controls = {
        'start_trading': start_trading,
        'stop_trading': stop_trading,
        'get_status': get_status,
    }
    telegram_bot = TelegramBot(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, app_controls)
    threading.Thread(target=telegram_bot.run, daemon=True).start()
    
    # Ожидаем инициализации бота
    await asyncio.sleep(2)
    await telegram_bot.send_message("🤖 **Робот запущен и готов к работе!**\n\nИспользуйте /start для начала торговли.")
    
    # Создаем контекст для клиента Tinkoff
    async with TinkoffClient(config.TINKOFF_API_TOKEN, config.USE_SANDBOX) as client:
        risk_manager = RiskManager(client)
        
        # Первоначальный выбор инструментов
        await select_top_volatile_instruments(client)
        risk_manager.reset_daily_counts()
        
        # Настройка ежедневного обновления инструментов и сброса счетчиков
        schedule.every().day.at("09:00").do(
            lambda: asyncio.run(select_top_volatile_instruments(client))
        )
        schedule.every().day.at("00:01").do(risk_manager.reset_daily_counts)
        
        # Основной цикл работы
        while True:
            schedule.run_pending() # Проверяем, не пора ли запустить запланированную задачу
            
            if trading_active:
                try:
                    await trading_cycle(client, risk_manager, strategy_manager)
                except Exception as e:
                    logging.error(f"Критическая ошибка в торговом цикле: {e}")
                    await telegram_bot.send_message(f"‼️ **Критическая ошибка:**\n`{e}`\nРобот продолжает работу.")
            
            await asyncio.sleep(15) # Пауза между итерациями цикла

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Программа завершена пользователем.")
    except Exception as e:
        logging.critical(f"Необработанная ошибка в main: {e}")
