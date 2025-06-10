# telegram_bot.py
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config

class TelegramBot:
    """
    Класс для управления Telegram-ботом. Отправляет уведомления и обрабатывает команды.
    """
    def __init__(self, token, chat_id, app_controls):
        self.application = Application.builder().token(token).build()
        self.chat_id = chat_id
        self.app_controls = app_controls # Ссылки на функции управления в main.py
        
        # Регистрация обработчиков команд
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("status", self.status_command))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start."""
        logging.info("Получена команда /start от пользователя.")
        self.app_controls['start_trading']()
        await update.message.reply_text('✅ Торговый робот запущен!')

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /stop."""
        logging.info("Получена команда /stop от пользователя.")
        self.app_controls['stop_trading']()
        await update.message.reply_text('🛑 Торговый робот остановлен.')
        
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /status."""
        status = self.app_controls['get_status']()
        await update.message.reply_text(status)

    async def send_message(self, text: str):
        """Отправляет сообщение в заданный чат."""
        try:
            await self.application.bot.send_message(chat_id=self.chat_id, text=text, parse_mode='HTML')
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение в Telegram: {e}")
            
    def run(self):
        """Запускает бота в режиме опроса."""
        logging.info("Telegram-бот запускается...")
        self.application.run_polling()
