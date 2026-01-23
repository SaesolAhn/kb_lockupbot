"""KB Lockup - Entry point and CLI commands"""

import asyncio
from typing import Optional

import click
from loguru import logger

from kb_lockup.config import settings


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """KB Lockup - Korean DART Lockup Schedule Extraction System"""
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
@click.argument("company_name")
def search(company_name: str) -> None:
    """Search lockup data for a company"""
    from kb_lockup.storage.database import Database

    async def _search():
        async with Database() as db:
            results = await db.search_lockup(company_name)
            if not results:
                click.echo(f"No lockup data found for '{company_name}'")
                return

            click.echo(f"\nLockup data for {company_name}:")
            click.echo("-" * 60)
            for entry in results:
                click.echo(f"Owner: {entry.owner}")
                click.echo(f"Amount: {entry.amount:,} shares ({entry.ratio}%)")
                click.echo(f"Release: {entry.release_date}")
                click.echo("-" * 60)

    asyncio.run(_search())


@cli.command()
@click.argument("company_name")
@click.option("--start-date", "-s", help="Start date (YYYYMMDD)")
@click.option("--end-date", "-e", help="End date (YYYYMMDD)")
@click.option("--force", "-f", is_flag=True, help="Re-extract even if already processed")
def extract(
    company_name: str,
    start_date: Optional[str],
    end_date: Optional[str],
    force: bool,
) -> None:
    """Extract lockup data from DART filings for a company"""
    from kb_lockup.extraction.pipeline import ExtractionPipeline

    async def _extract():
        click.echo(f"Extracting lockup data for {company_name}...")

        async with ExtractionPipeline() as pipeline:
            try:
                result = await pipeline.extract_company(
                    company_name,
                    start_date=start_date,
                    end_date=end_date,
                    force=force,
                )

                if not result.entries:
                    click.echo("No lockup entries found.")
                    return

                click.echo(f"\nExtracted {len(result.entries)} entries:")
                click.echo("-" * 60)

                for entry in result.entries:
                    click.echo(f"Owner: {entry.owner}")
                    if entry.amount:
                        click.echo(f"  Amount: {entry.amount:,} shares")
                    if entry.ratio:
                        click.echo(f"  Ratio: {entry.ratio:.2f}%")
                    if entry.release_date:
                        click.echo(f"  Release: {entry.release_date}")
                    click.echo()

                stats = pipeline.get_stats()
                click.echo(f"Stats: {stats['documents_processed']} docs, "
                          f"{stats['tables_found']} tables, "
                          f"{stats['api_requests']} API calls")

            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                raise click.Abort()

    asyncio.run(_extract())


@cli.command()
@click.option("--days", "-d", default=30, help="Days to look ahead")
def upcoming(days: int) -> None:
    """List upcoming lockup releases"""
    from kb_lockup.storage.database import Database

    async def _upcoming():
        async with Database() as db:
            results = await db.get_upcoming_unlocks(days)
            if not results:
                click.echo(f"No upcoming unlocks in the next {days} days")
                return

            click.echo(f"\nUpcoming unlocks (next {days} days):")
            click.echo("-" * 60)
            for entry in results:
                click.echo(f"{entry.company_name} | {entry.owner}")
                click.echo(f"  {entry.amount:,} shares | Release: {entry.release_date}")
                click.echo("-" * 60)

    asyncio.run(_upcoming())


@cli.command()
def init_db() -> None:
    """Initialize the database schema"""
    from kb_lockup.storage.database import Database

    async def _init():
        async with Database() as db:
            await db.init_schema()
            click.echo("Database initialized successfully")

    asyncio.run(_init())


@cli.command()
def bot() -> None:
    """Run the Telegram bot"""
    from kb_lockup.telegram_bot.bot import KBLockupBot

    if not settings.telegram_bot_token:
        click.echo("Error: TELEGRAM_BOT_TOKEN not set in .env", err=True)
        raise click.Abort()

    click.echo("Starting Telegram bot...")
    bot = KBLockupBot()
    bot.run()


@cli.command()
def web() -> None:
    """Run the Streamlit web interface"""
    import subprocess
    import sys

    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        "kb_lockup/web/app.py",
        "--server.headless", "true",
    ])


@cli.command()
def stats() -> None:
    """Show database statistics"""
    from kb_lockup.storage.database import Database

    async def _stats():
        async with Database() as db:
            s = await db.get_stats()

            click.echo("\n📊 KB Lockup Statistics")
            click.echo("=" * 40)
            click.echo(f"Total lockup entries:    {s['total_lockups']:,}")
            click.echo(f"Unique companies:        {s['unique_companies']:,}")
            click.echo(f"Processed prospectuses:  {s['processed_prospectuses']:,}")
            click.echo(f"Failed prospectuses:     {s['failed_prospectuses']:,}")
            click.echo(f"Active reminders:        {s['active_reminders']:,}")
            click.echo(f"Upcoming unlocks (30d):  {s['upcoming_unlocks_30d']:,}")
            click.echo("=" * 40)

    asyncio.run(_stats())


@cli.command("search-company")
@click.argument("query")
def search_company(query: str) -> None:
    """Search for a company in DART"""
    from kb_lockup.dart.api import DartAPI

    async def _search():
        async with DartAPI() as api:
            companies = await api.search_company(query)

            if not companies:
                click.echo(f"No companies found matching '{query}'")
                return

            click.echo(f"\nFound {len(companies)} companies:")
            click.echo("-" * 50)
            for c in companies:
                stock = f" ({c.stock_code})" if c.stock_code else ""
                click.echo(f"{c.corp_name}{stock}")
                click.echo(f"  Corp code: {c.corp_code}")

    asyncio.run(_search())


@cli.command("extract-ipos")
@click.option("--days", "-d", default=90, help="Look back period in days")
def extract_ipos(days: int) -> None:
    """Extract lockup data from recent IPO prospectuses"""
    from kb_lockup.extraction.pipeline import ExtractionPipeline

    async def _extract():
        click.echo(f"Searching for IPO prospectuses from the last {days} days...")

        async with ExtractionPipeline() as pipeline:
            results = await pipeline.extract_recent_ipos(days=days)

            click.echo(f"\nProcessed {len(results)} IPO prospectuses")

            total_entries = sum(len(r.entries) for r in results)
            click.echo(f"Total entries extracted: {total_entries}")

            stats = pipeline.get_stats()
            click.echo(f"\nStats:")
            click.echo(f"  Documents: {stats['documents_processed']}")
            click.echo(f"  Tables found: {stats['tables_found']}")
            click.echo(f"  API requests: {stats['api_requests']}")
            click.echo(f"  Errors: {stats['errors']}")

    asyncio.run(_extract())


if __name__ == "__main__":
    cli()
