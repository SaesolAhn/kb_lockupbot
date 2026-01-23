"""Message formatting for Telegram and other outputs"""

from datetime import date
from typing import List, Optional

from kb_lockup.core.models import LockupData, LockupEntry, ExitOpportunity


class MessageFormatter:
    """Format lockup data for display"""

    @staticmethod
    def format_lockup_message(
        company_name: str,
        stock_code: Optional[str],
        entries: List[LockupData],
    ) -> str:
        """
        Format lockup data for Telegram message

        Returns:
            Formatted message string
        """
        if not entries:
            return f"'{company_name}'에 대한 보호예수 정보가 없습니다."

        lines = []

        # Header
        code_str = f" ({stock_code})" if stock_code else ""
        lines.append(f"📊 **{company_name}{code_str} 보호예수 현황**\n")

        # Entries
        for entry in entries:
            lines.append("┌─────────────────────────────────")
            lines.append(f"│ 주주명: {entry.owner}")

            if entry.amount:
                ratio_str = f" ({entry.ratio:.2f}%)" if entry.ratio else ""
                lines.append(f"│ 보유량: {entry.amount:,}주{ratio_str}")

            if entry.release_date:
                days = (entry.release_date - date.today()).days
                if days > 0:
                    lines.append(f"│ 해제일: {entry.release_date} (D-{days})")
                elif days == 0:
                    lines.append(f"│ 해제일: {entry.release_date} (D-Day)")
                else:
                    lines.append(f"│ 해제일: {entry.release_date} (해제됨)")

            if entry.remarks:
                lines.append(f"│ 비고: {entry.remarks}")

            lines.append("└─────────────────────────────────\n")

        # Footer
        lines.append(f"총 {len(entries)}건 | 업데이트: {date.today()}")

        return "\n".join(lines)

    @staticmethod
    def format_upcoming_message(
        entries: List[LockupData],
        days: int,
    ) -> str:
        """Format upcoming unlocks message"""
        if not entries:
            return f"향후 {days}일 내 해제되는 보호예수가 없습니다."

        lines = [f"📅 **향후 {days}일 보호예수 해제 예정**\n"]

        for entry in entries:
            days_until = (entry.release_date - date.today()).days if entry.release_date else 0

            lines.append(f"• **{entry.company_name}** - {entry.owner}")
            if entry.amount:
                lines.append(f"  {entry.amount:,}주 ({entry.ratio:.1f}%)")
            lines.append(f"  해제: {entry.release_date} (D-{days_until})")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_opportunity_message(
        opportunities: List[ExitOpportunity],
        title: str = "블록딜 기회",
    ) -> str:
        """Format opportunity analysis message"""
        if not opportunities:
            return "해당 조건의 기회가 없습니다."

        lines = [f"💰 **{title}**\n"]

        for opp in opportunities[:10]:  # Limit to top 10
            lines.append(f"• **{opp.company_name}**")
            lines.append(f"  주주: {opp.owner}")
            lines.append(f"  {opp.amount:,}주 ({opp.ratio:.1f}%)")
            lines.append(f"  해제: {opp.release_date} (D-{opp.days_until_unlock})")

            if opp.opportunity_score:
                lines.append(f"  점수: {opp.opportunity_score:.1f}")

            lines.append("")

        if len(opportunities) > 10:
            lines.append(f"... 외 {len(opportunities) - 10}건")

        return "\n".join(lines)

    @staticmethod
    def format_reminder_list(
        reminders: list,
        chat_id: int,
    ) -> str:
        """Format reminder list message"""
        if not reminders:
            return "등록된 알림이 없습니다."

        lines = ["🔔 **등록된 알림 목록**\n"]

        for i, r in enumerate(reminders, 1):
            target = r.company_name or r.stock_code or "전체"
            lines.append(f"{i}. {target}")
            lines.append(f"   최소 지분율: {r.min_ratio}%")
            lines.append(f"   알림: 해제 {r.days_before}일 전")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_search_result_brief(
        entries: List[LockupData],
    ) -> str:
        """Format brief search result for inline display"""
        if not entries:
            return "결과 없음"

        lines = []
        for entry in entries[:5]:
            days = ""
            if entry.release_date:
                d = (entry.release_date - date.today()).days
                days = f" D-{d}" if d > 0 else " 해제됨"

            lines.append(
                f"{entry.company_name} | {entry.owner} | "
                f"{entry.amount:,}주{days}"
            )

        if len(entries) > 5:
            lines.append(f"... 외 {len(entries) - 5}건")

        return "\n".join(lines)

    @staticmethod
    def format_error_message(error: str) -> str:
        """Format error message"""
        return f"⚠️ 오류가 발생했습니다: {error}"

    @staticmethod
    def format_help_message() -> str:
        """Format help message for Telegram bot"""
        return """🔒 **KB Lockup Bot 사용법**

**검색**
/search <회사명 또는 종목코드>
예: /search 삼성전자

**다가오는 해제**
/upcoming [일수]
예: /upcoming 30

**알림 설정**
/remind <회사명> <일수>
예: /remind 카카오 7

**알림 관리**
/reminders - 알림 목록
/cancel <번호> - 알림 취소

**분석**
/blockdeal [최소지분율]
예: /blockdeal 5

**내보내기**
/export <회사명>
예: /export 네이버

/help - 이 도움말
"""
