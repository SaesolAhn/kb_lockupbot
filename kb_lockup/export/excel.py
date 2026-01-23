"""Excel export and xlwings add-in functions"""

from datetime import date
from pathlib import Path
from typing import List, Optional

import pandas as pd
from loguru import logger

from kb_lockup.config import settings
from kb_lockup.core.models import LockupData, ExitOpportunity


class ExcelExporter:
    """Export lockup data to Excel files"""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or settings.export_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_lockup_data(
        self,
        data: List[LockupData],
        filename: Optional[str] = None,
    ) -> Path:
        """
        Export lockup data to Excel file

        Args:
            data: List of LockupData objects
            filename: Output filename (auto-generated if not provided)

        Returns:
            Path to created file
        """
        if not filename:
            filename = f"lockup_export_{date.today().isoformat()}.xlsx"

        filepath = self.output_dir / filename

        # Convert to DataFrame
        df = pd.DataFrame([
            {
                "회사명": d.company_name,
                "종목코드": d.stock_code,
                "주주명": d.owner,
                "보유량": d.amount,
                "지분율(%)": d.ratio,
                "해제일": d.release_date.isoformat() if d.release_date else None,
                "보호예수기간(개월)": d.lock_period_months,
                "비고": d.remarks,
            }
            for d in data
        ])

        # Write to Excel with formatting
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="보호예수현황", index=False)

            # Auto-adjust column widths
            worksheet = writer.sheets["보호예수현황"]
            for idx, col in enumerate(df.columns):
                max_length = max(
                    df[col].astype(str).map(len).max(),
                    len(col)
                ) + 2
                worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)

        logger.info(f"Exported {len(data)} records to {filepath}")
        return filepath

    def export_opportunities(
        self,
        opportunities: List[ExitOpportunity],
        filename: Optional[str] = None,
    ) -> Path:
        """Export exit opportunities to Excel"""
        if not filename:
            filename = f"opportunities_{date.today().isoformat()}.xlsx"

        filepath = self.output_dir / filename

        df = pd.DataFrame([
            {
                "회사명": o.company_name,
                "종목코드": o.stock_code,
                "주주명": o.owner,
                "보유량": o.amount,
                "지분율(%)": o.ratio,
                "해제일": o.release_date.isoformat(),
                "D-Day": o.days_until_unlock,
                "추정가치": o.value_estimate,
                "일평균거래량": o.avg_daily_volume,
                "예상청산일수": o.days_to_exit,
                "점수": o.opportunity_score,
            }
            for o in opportunities
        ])

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="기회분석", index=False)

        logger.info(f"Exported {len(opportunities)} opportunities to {filepath}")
        return filepath

    def export_company_report(
        self,
        company_name: str,
        lockups: List[LockupData],
        filename: Optional[str] = None,
    ) -> Path:
        """Export detailed company report"""
        if not filename:
            safe_name = company_name.replace(" ", "_")
            filename = f"{safe_name}_report_{date.today().isoformat()}.xlsx"

        filepath = self.output_dir / filename

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            # Summary sheet
            summary_df = pd.DataFrame([{
                "회사명": company_name,
                "총 보호예수 건수": len(lockups),
                "총 주식수": sum(entry.amount or 0 for entry in lockups),
                "총 지분율": sum(entry.ratio or 0 for entry in lockups),
                "가장 빠른 해제일": min(
                    (entry.release_date for entry in lockups if entry.release_date),
                    default=None
                ),
            }])
            summary_df.to_excel(writer, sheet_name="요약", index=False)

            # Detail sheet
            detail_df = pd.DataFrame([
                {
                    "주주명": entry.owner,
                    "보유량": entry.amount,
                    "지분율(%)": entry.ratio,
                    "해제일": entry.release_date.isoformat() if entry.release_date else None,
                    "기간(개월)": entry.lock_period_months,
                    "비고": entry.remarks,
                }
                for entry in lockups
            ])
            detail_df.to_excel(writer, sheet_name="상세내역", index=False)

        return filepath


# xlwings UDF functions (for Excel add-in)
try:
    import xlwings as xw

    @xw.func
    def kb_lockup_search(company_name: str) -> list:
        """
        Excel function: =kb_lockup_search("삼성전자")

        Returns lockup data as a 2D array for Excel
        """
        import asyncio
        from kb_lockup.storage.database import Database

        async def _search():
            async with Database() as db:
                return await db.search_lockup(company_name)

        results = asyncio.run(_search())
        return [
            [r.owner, r.amount, r.ratio, str(r.release_date) if r.release_date else ""]
            for r in results
        ]

    @xw.func
    def kb_upcoming_unlocks(days: int = 30) -> list:
        """
        Excel function: =kb_upcoming_unlocks(30)

        Returns upcoming unlocks as a 2D array
        """
        import asyncio
        from kb_lockup.storage.database import Database

        async def _upcoming():
            async with Database() as db:
                return await db.get_upcoming_unlocks(days)

        results = asyncio.run(_upcoming())
        return [
            [r.company_name, r.owner, r.amount, str(r.release_date) if r.release_date else ""]
            for r in results
        ]

except ImportError:
    # xlwings not installed, skip UDF registration
    pass
