# config.py
import os
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

# --- Настройки API и Бота ---
# Используем os.getenv для безопасного получения ключей из окружения
TINKOFF_API_TOKEN = os.getenv("TINKOFF_API_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TINKOFF_ACCOUNT_ID = os.getenv("TINKOFF_ACCOUNT_ID")

# --- Настройки торговли ---
# Использовать "песочницу" (демо-счет) или реальный счет
USE_SANDBOX = True 

# --- Настройки выбора инструментов ---
# Количество самых волатильных инструментов для торговли
TOP_VOLATILE_INSTRUMENTS_COUNT = 10
# Период в днях для расчета волатильности (ATR)
VOLATILITY_PERIOD_DAYS = 30

# --- Настройки управления рисками ---
# Доля депозита, которой рискуем в одной сделке (1% = 0.01)
RISK_PER_TRADE = 0.01
# Соотношение Take Profit к Stop Loss (например, 2:1)
TAKE_PROFIT_RATIO = 2.0
# Процент от цены для установки Stop Loss (например, 0.5% = 0.005)
STOP_LOSS_PERCENT = 0.005
# Максимальное количество сделок в день по одному инструменту
MAX_TRADES_PER_INSTRUMENT_PER_DAY = 5

# --- Параметры адаптивных стратегий ---
# Пороговое значение ADX для определения тренда
ADX_TREND_THRESHOLD = 25

# --- Параметры стратегии "Пересечение скользящих средних" (для тренда) ---
MA_FAST_PERIOD = 9
MA_SLOW_PERIOD = 21

# --- Параметры стратегии "Ленты Боллинджера + RSI" (для боковика) ---
BB_PERIOD = 20
BB_STD_DEV = 2
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# --- Настройки обработки ошибок ---
API_RETRY_COUNT = 3
API_RETRY_DELAY_SECONDS = 5
API_REQUEST_TIMEOUT_SECONDS = 10
