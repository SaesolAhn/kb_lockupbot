"""Telegram bot main handler"""

from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from loguru import logger

from kb_lockup.config import settings
from kb_lockup.storage.database import Database
from kb_lockup.telegram_bot.commands import CommandHandlers
from kb_lockup.telegram_bot.scheduler import ReminderScheduler


class KBLockupBot:
    """KB Lockup Telegram Bot"""

    def __init__(
        self,
        token: Optional[str] = None,
        db_path: Optional[str] = None,
    ):
        self.token = token or settings.telegram_bot_token
        if not self.token:
            raise ValueError("Telegram bot token is required")

        self.db_path = db_path
        self.app: Optional[Application] = None
        self.scheduler: Optional[ReminderScheduler] = None
        self._handlers: Optional[CommandHandlers] = None

    async def setup(self) -> None:
        """Initialize bot application"""
        self.app = Application.builder().token(self.token).build()
        self._handlers = CommandHandlers(self.db_path)
        self.scheduler = ReminderScheduler(self.db_path, self.app.bot)

        self._setup_handlers()
        logger.info("Telegram bot initialized")

    def _setup_handlers(self) -> None:
        """Register command handlers"""
        if not self.app or not self._handlers:
            raise RuntimeError("Bot not initialized")

        handlers = [
            CommandHandler("start", self._handlers.start_handler),
            CommandHandler("help", self._handlers.help_handler),
            CommandHandler("search", self._handlers.search_handler),
            CommandHandler("upcoming", self._handlers.upcoming_handler),
            CommandHandler("remind", self._handlers.remind_handler),
            CommandHandler("reminders", self._handlers.reminders_handler),
            CommandHandler("cancel", self._handlers.cancel_handler),
            CommandHandler("blockdeal", self._handlers.blockdeal_handler),
            CommandHandler("export", self._handlers.export_handler),
            CallbackQueryHandler(self._handlers.button_handler),
        ]

        for handler in handlers:
            self.app.add_handler(handler)

        # Error handler
        self.app.add_error_handler(self._error_handler)

    async def _error_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle errors"""
        logger.error(f"Update {update} caused error: {context.error}")

        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            )

    async def start(self) -> None:
        """Start the bot"""
        if not self.app:
            await self.setup()

        # Start scheduler
        if self.scheduler:
            self.scheduler.start()

        logger.info("Starting Telegram bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        """Stop the bot"""
        if self.scheduler:
            self.scheduler.stop()

        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

        logger.info("Telegram bot stopped")

    def run(self) -> None:
        """Run the bot (blocking)"""
        import asyncio

        async def _run():
            await self.setup()
            await self.start()

            # Keep running until interrupted
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            finally:
                await self.stop()

        asyncio.run(_run())
