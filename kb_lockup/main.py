"""KB Lockup - Entry point and CLI commands"""

import asyncio
import click
import sys
import subprocess
from loguru import logger
from datetime import date, datetime

from kb_lockup.config import settings

@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """KB Lockup - SEIBro Unstaking Schedule & Block Deal Analysis"""
    log_level = "DEBUG" if verbose else settings.log_level
    logger.remove()
    logger.add(
        lambda msg: click.echo(msg, nl=False),
        level=log_level,
        format="<level>{level: <8}</level> | {message}",
        colorize=True,
    )
    settings.ensure_directories()

@cli.command()
def web() -> None:
    """Run the Streamlit web interface"""
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        "kb_lockup/web/app.py",
        "--server.headless", "true",
    ])

@cli.command("analyze-block-deals")
@click.option("--limit", "-n", default=100, help="Number of items to analyze")
def analyze_block_deals(limit: int) -> None:
    """Run AI Block Deal Analysis on recent unstaking events"""
    from kb_lockup.seibro.db_utils import get_db_session
    from kb_lockup.seibro.models import SeibroUnstakingSchedule
    from kb_lockup.analysis.block_deal_ai import BlockDealAnalyzer
    from sqlalchemy import select

    def _analyze():
        # Sync wrapper since we are using sync sqlalchemy for seibro
        analyzer = BlockDealAnalyzer()
        
        with get_db_session() as session:
            # Fetch items with value > 100M KRW and no score yet
            query = select(SeibroUnstakingSchedule).where(
                SeibroUnstakingSchedule.current_stake_value_million_krw > 100,
                SeibroUnstakingSchedule.block_deal_score == None
            ).limit(limit)
            
            items = session.execute(query).scalars().all()
            
            if not items:
                click.echo("No pending items for analysis.")
                return

            click.echo(f"Analyzing {len(items)} items...")
            
            count = 0
            for item in items:
                click.echo(f"Analyzing {item.company_name} ({item.reason})...")
                score, reason = analyzer.analyze_row({
                    "company_name": item.company_name,
                    "reason": item.reason,
                    "return_shares": item.return_shares,
                    "stake_portion_pct": float(item.stake_portion_pct) if item.stake_portion_pct else 0,
                    "current_stake_value_million_krw": float(item.current_stake_value_million_krw) if item.current_stake_value_million_krw else 0,
                    "total_shares": item.total_shares
                })
                
                if score is not None:
                    item.block_deal_score = score
                    item.block_deal_analysis = reason
                    count += 1
            
            session.commit()
            click.echo(f"Analysis complete. Updated {count} items.")

    # Since our seibro db_utils is sync, we don't strictly need asyncio run here, 
    # but maintaining structure.
    _analyze()

if __name__ == "__main__":
    cli()
