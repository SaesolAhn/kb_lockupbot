"""Threshold-based alerting logic"""

from datetime import date, timedelta
from typing import List, Optional, Callable, Awaitable

from loguru import logger

from kb_lockup.core.models import LockupData, ReminderConfig
from kb_lockup.storage.database import Database


class AlertManager:
    """Manage and trigger alerts based on lockup schedules"""

    def __init__(self, db: Database):
        self.db = db
        self._alert_handlers: List[Callable[[LockupData, ReminderConfig], Awaitable[None]]] = []

    def register_handler(
        self,
        handler: Callable[[LockupData, ReminderConfig], Awaitable[None]],
    ) -> None:
        """Register an alert handler function"""
        self._alert_handlers.append(handler)

    async def check_reminders(self) -> List[tuple]:
        """
        Check all active reminders and trigger alerts

        Returns:
            List of (lockup, reminder) tuples that triggered
        """
        reminders = await self.db.get_reminders(active_only=True)
        triggered = []

        for reminder in reminders:
            matches = await self._find_matching_unlocks(reminder)
            for lockup in matches:
                triggered.append((lockup, reminder))
                await self._trigger_alert(lockup, reminder)

        if triggered:
            logger.info(f"Triggered {len(triggered)} alerts")

        return triggered

    async def _find_matching_unlocks(
        self,
        reminder: ReminderConfig,
    ) -> List[LockupData]:
        """Find unlocks matching a reminder's criteria"""
        # Calculate the target date range
        target_date = date.today() + timedelta(days=reminder.days_before)

        # Get upcoming unlocks
        unlocks = await self.db.get_upcoming_unlocks(
            days=reminder.days_before + 1,
            min_ratio=reminder.min_ratio,
        )

        matches = []
        for lockup in unlocks:
            if not lockup.release_date:
                continue

            # Check if release date matches target
            if lockup.release_date != target_date:
                continue

            # Filter by company if specified
            if reminder.company_name:
                if reminder.company_name not in lockup.company_name:
                    continue

            # Filter by stock code if specified
            if reminder.stock_code:
                if lockup.stock_code != reminder.stock_code:
                    continue

            # Filter by owner if specified
            if reminder.owner:
                if reminder.owner not in lockup.owner:
                    continue

            # Filter by minimum amount if specified
            if reminder.min_amount:
                if not lockup.amount or lockup.amount < reminder.min_amount:
                    continue

            matches.append(lockup)

        return matches

    async def _trigger_alert(
        self,
        lockup: LockupData,
        reminder: ReminderConfig,
    ) -> None:
        """Trigger alert handlers for a matching lockup"""
        for handler in self._alert_handlers:
            try:
                await handler(lockup, reminder)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")

    async def get_upcoming_alerts(
        self,
        chat_id: int,
        days: int = 7,
    ) -> List[dict]:
        """
        Preview upcoming alerts for a user

        Args:
            chat_id: Telegram chat ID
            days: Days to look ahead

        Returns:
            List of dicts with lockup and reminder info
        """
        reminders = await self.db.get_reminders(chat_id=chat_id, active_only=True)
        results = []

        for reminder in reminders:
            # Temporarily adjust days_before to check full range
            original_days = reminder.days_before
            reminder.days_before = days

            matches = await self._find_matching_unlocks(reminder)
            for lockup in matches:
                results.append({
                    "lockup": lockup,
                    "reminder": reminder,
                    "days_until_alert": (
                        lockup.release_date - date.today()
                    ).days - original_days if lockup.release_date else None,
                })

            reminder.days_before = original_days

        return results

    async def add_reminder(
        self,
        chat_id: int,
        company_name: Optional[str] = None,
        stock_code: Optional[str] = None,
        days_before: int = 7,
        min_ratio: float = 1.0,
    ) -> int:
        """
        Add a new reminder subscription

        Returns:
            Reminder ID
        """
        reminder = ReminderConfig(
            telegram_chat_id=chat_id,
            company_name=company_name,
            stock_code=stock_code,
            days_before=days_before,
            min_ratio=min_ratio,
        )

        reminder_id = await self.db.add_reminder(reminder)
        logger.info(f"Added reminder {reminder_id} for chat {chat_id}")
        return reminder_id
