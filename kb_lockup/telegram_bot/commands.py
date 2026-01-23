"""Telegram bot command handlers"""

from typing import Optional
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from loguru import logger

from kb_lockup.storage.database import Database
from kb_lockup.analysis.blockdeal import BlockdealAnalyzer
from kb_lockup.analysis.alerts import AlertManager
from kb_lockup.export.excel import ExcelExporter
from kb_lockup.export.formatter import MessageFormatter


class CommandHandlers:
    """Command handler implementations"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    async def _get_db(self) -> Database:
        """Get database connection"""
        db = Database(Path(self.db_path) if self.db_path else None)
        await db.connect()
        return db

    async def start_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /start command"""
        await update.message.reply_text(
            "🔒 KB Lockup Bot에 오신 것을 환영합니다!\n\n"
            "한국 상장사의 보호예수 일정을 조회하고 알림을 받을 수 있습니다.\n\n"
            "/help 명령어로 사용법을 확인하세요."
        )

    async def help_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /help command"""
        await update.message.reply_text(
            MessageFormatter.format_help_message(),
            parse_mode="Markdown",
        )

    async def search_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /search command"""
        if not context.args:
            await update.message.reply_text(
                "사용법: /search <회사명 또는 종목코드>\n"
                "예: /search 삼성전자"
            )
            return

        query = " ".join(context.args)
        db = await self._get_db()

        try:
            results = await db.search_lockup(query)

            if not results:
                await update.message.reply_text(
                    f"'{query}'에 대한 검색 결과가 없습니다."
                )
                return

            # Get company info from first result
            company_name = results[0].company_name
            stock_code = results[0].stock_code

            message = MessageFormatter.format_lockup_message(
                company_name=company_name,
                stock_code=stock_code,
                entries=results,
            )

            await update.message.reply_text(message, parse_mode="Markdown")

        finally:
            await db.close()

    async def upcoming_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /upcoming command"""
        days = 30
        if context.args:
            try:
                days = int(context.args[0])
            except ValueError:
                await update.message.reply_text("일수는 숫자로 입력해주세요.")
                return

        db = await self._get_db()

        try:
            results = await db.get_upcoming_unlocks(days=days)
            message = MessageFormatter.format_upcoming_message(results, days)
            await update.message.reply_text(message, parse_mode="Markdown")
        finally:
            await db.close()

    async def remind_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /remind command"""
        if len(context.args) < 2:
            await update.message.reply_text(
                "사용법: /remind <회사명> <일수>\n"
                "예: /remind 카카오 7"
            )
            return

        company_name = context.args[0]
        try:
            days_before = int(context.args[1])
        except ValueError:
            await update.message.reply_text("일수는 숫자로 입력해주세요.")
            return

        db = await self._get_db()

        try:
            alert_manager = AlertManager(db)
            chat_id = update.effective_chat.id

            reminder_id = await alert_manager.add_reminder(
                chat_id=chat_id,
                company_name=company_name,
                days_before=days_before,
            )

            await update.message.reply_text(
                f"✅ 알림이 등록되었습니다!\n\n"
                f"회사: {company_name}\n"
                f"알림: 해제 {days_before}일 전"
            )
        finally:
            await db.close()

    async def reminders_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /reminders command"""
        db = await self._get_db()

        try:
            chat_id = update.effective_chat.id
            reminders = await db.get_reminders(chat_id=chat_id, active_only=True)

            message = MessageFormatter.format_reminder_list(reminders, chat_id)
            await update.message.reply_text(message, parse_mode="Markdown")
        finally:
            await db.close()

    async def cancel_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /cancel command"""
        if not context.args:
            await update.message.reply_text(
                "사용법: /cancel <알림번호>\n"
                "/reminders 명령어로 알림 목록을 확인하세요."
            )
            return

        try:
            reminder_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("알림 번호를 숫자로 입력해주세요.")
            return

        db = await self._get_db()

        try:
            success = await db.deactivate_reminder(reminder_id)
            if success:
                await update.message.reply_text(f"✅ 알림 #{reminder_id}가 취소되었습니다.")
            else:
                await update.message.reply_text("해당 알림을 찾을 수 없습니다.")
        finally:
            await db.close()

    async def blockdeal_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /blockdeal command"""
        min_ratio = 5.0
        if context.args:
            try:
                min_ratio = float(context.args[0])
            except ValueError:
                await update.message.reply_text("지분율은 숫자로 입력해주세요.")
                return

        db = await self._get_db()

        try:
            analyzer = BlockdealAnalyzer(db)
            opportunities = await analyzer.find_opportunities(
                days_ahead=30,
                min_ratio=min_ratio,
            )

            message = MessageFormatter.format_opportunity_message(
                opportunities,
                title=f"블록딜 기회 (지분율 {min_ratio}% 이상)",
            )
            await update.message.reply_text(message, parse_mode="Markdown")
        finally:
            await db.close()

    async def export_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /export command"""
        if not context.args:
            await update.message.reply_text(
                "사용법: /export <회사명>\n"
                "예: /export 네이버"
            )
            return

        company_name = " ".join(context.args)
        db = await self._get_db()

        try:
            results = await db.get_lockup_by_company(company_name)

            if not results:
                await update.message.reply_text(
                    f"'{company_name}'에 대한 데이터가 없습니다."
                )
                return

            # Export to Excel
            exporter = ExcelExporter()
            filepath = exporter.export_company_report(company_name, results)

            # Send file
            await update.message.reply_document(
                document=open(filepath, "rb"),
                filename=filepath.name,
                caption=f"📊 {company_name} 보호예수 현황",
            )
        finally:
            await db.close()

    async def button_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle inline button callbacks"""
        query = update.callback_query
        await query.answer()

        data = query.data
        logger.debug(f"Button callback: {data}")

        # Handle different button actions
        if data.startswith("search:"):
            company = data.split(":", 1)[1]
            # Simulate search command
            context.args = [company]
            await self.search_handler(update, context)

        elif data.startswith("remind:"):
            company = data.split(":", 1)[1]
            await query.message.reply_text(
                f"알림 설정: /remind {company} <일수>"
            )
