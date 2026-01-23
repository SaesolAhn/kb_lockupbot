"""Reminder scheduling with APScheduler"""

from typing import Optional
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot
from loguru import logger

from kb_lockup.config import settings
from kb_lockup.storage.database import Database
from kb_lockup.analysis.alerts import AlertManager
from kb_lockup.export.formatter import MessageFormatter


class ReminderScheduler:
    """Schedule and send reminder notifications"""

    def __init__(
        self,
        db_path: Optional[str] = None,
        bot: Optional[Bot] = None,
    ):
        self.db_path = db_path
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone=settings.reminder_timezone)
        self._setup_jobs()

    def _setup_jobs(self) -> None:
        """Configure scheduled jobs"""
        # Daily reminder check at configured hour
        self.scheduler.add_job(
            self.check_and_send_reminders,
            CronTrigger(
                hour=settings.reminder_check_hour,
                minute=0,
                timezone=settings.reminder_timezone,
            ),
            id="daily_reminders",
            replace_existing=True,
        )

        # Weekly digest on Monday morning
        self.scheduler.add_job(
            self.send_weekly_digest,
            CronTrigger(
                day_of_week="mon",
                hour=9,
                minute=0,
                timezone=settings.reminder_timezone,
            ),
            id="weekly_digest",
            replace_existing=True,
        )

        logger.info(
            f"Scheduled daily reminder check at {settings.reminder_check_hour}:00 "
            f"({settings.reminder_timezone})"
        )
        logger.info("Scheduled weekly digest on Monday 9:00 AM")

    def start(self) -> None:
        """Start the scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Reminder scheduler started")

    def stop(self) -> None:
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Reminder scheduler stopped")

    async def check_and_send_reminders(self) -> int:
        """
        Check all reminders and send notifications

        Returns:
            Number of notifications sent
        """
        if not self.bot:
            logger.warning("Bot not configured, skipping reminder check")
            return 0

        db = Database(Path(self.db_path) if self.db_path else None)
        await db.connect()

        try:
            alert_manager = AlertManager(db)
            triggered = await alert_manager.check_reminders()

            sent_count = 0
            for lockup, reminder in triggered:
                try:
                    message = self._format_reminder_message(lockup, reminder)
                    await self.bot.send_message(
                        chat_id=reminder.telegram_chat_id,
                        text=message,
                        parse_mode="Markdown",
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(
                        f"Failed to send reminder to {reminder.telegram_chat_id}: {e}"
                    )

            logger.info(f"Sent {sent_count} reminder notifications")
            return sent_count

        finally:
            await db.close()

    def _format_reminder_message(self, lockup, reminder) -> str:
        """Format reminder notification message"""
        from datetime import date

        days_until = (lockup.release_date - date.today()).days if lockup.release_date else 0

        lines = [
            "🔔 **보호예수 해제 알림**\n",
            f"**{lockup.company_name}**",
            f"주주: {lockup.owner}",
        ]

        if lockup.amount:
            lines.append(f"보유량: {lockup.amount:,}주 ({lockup.ratio:.1f}%)")

        lines.append(f"해제일: {lockup.release_date} (D-{days_until})")

        return "\n".join(lines)

    async def send_weekly_digest(self) -> int:
        """
        Send weekly digest to subscribed users

        Returns:
            Number of digests sent
        """
        if not self.bot:
            logger.warning("Bot not configured, skipping weekly digest")
            return 0

        db = Database(Path(self.db_path) if self.db_path else None)
        await db.connect()

        try:
            # Get upcoming unlocks for next 7 days
            from datetime import date
            unlocks = await db.get_upcoming_unlocks(days=7)

            if not unlocks:
                logger.info("No upcoming unlocks for weekly digest")
                return 0

            # Get all active reminders to find subscribed chats
            reminders = await db.get_reminders(active_only=True)
            chat_ids = set(r.telegram_chat_id for r in reminders)

            if not chat_ids:
                logger.info("No subscribers for weekly digest")
                return 0

            # Format digest message
            message = self._format_weekly_digest(unlocks)

            # Send to all subscribed chats
            sent_count = 0
            for chat_id in chat_ids:
                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown",
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Failed to send digest to {chat_id}: {e}")

            logger.info(f"Sent weekly digest to {sent_count} chats")
            return sent_count

        finally:
            await db.close()

    def _format_weekly_digest(self, unlocks: list) -> str:
        """Format weekly digest message"""
        from datetime import date

        lines = [
            "📅 **주간 보호예수 해제 예정**\n",
            "다음 7일간 해제 예정입니다:\n",
        ]

        for lockup in unlocks[:15]:  # Limit to 15 items
            days = (lockup.release_date - date.today()).days if lockup.release_date else 0

            entry = f"• **{lockup.company_name}** - {lockup.owner}"
            if lockup.amount:
                entry += f"\n  {lockup.amount:,}주"
                if lockup.ratio:
                    entry += f" ({lockup.ratio:.1f}%)"
            entry += f"\n  D-{days}"
            lines.append(entry)
            lines.append("")

        if len(unlocks) > 15:
            lines.append(f"... 외 {len(unlocks) - 15}건\n")

        lines.append("/upcoming 명령어로 더 자세한 정보를 확인하세요.")

        return "\n".join(lines)

    async def send_immediate_reminder(
        self,
        chat_id: int,
        message: str,
    ) -> bool:
        """Send an immediate reminder message"""
        if not self.bot:
            logger.warning("Bot not configured")
            return False

        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send immediate reminder: {e}")
            return False

    def add_one_time_job(
        self,
        func,
        run_date,
        job_id: str,
        **kwargs,
    ) -> None:
        """Add a one-time scheduled job"""
        from apscheduler.triggers.date import DateTrigger

        self.scheduler.add_job(
            func,
            DateTrigger(run_date=run_date),
            id=job_id,
            replace_existing=True,
            kwargs=kwargs,
        )

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job"""
        try:
            self.scheduler.remove_job(job_id)
            return True
        except Exception:
            return False

    def get_jobs(self) -> list:
        """Get list of scheduled jobs"""
        return self.scheduler.get_jobs()
