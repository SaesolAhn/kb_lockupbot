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


@cli.command("api-status")
def api_status() -> None:
    """Show DART API usage status"""
    from kb_lockup.dart.api import get_daily_request_count, get_remaining_requests, CORP_CODES_CACHE_FILE
    import time

    count = get_daily_request_count()
    remaining = get_remaining_requests()
    limit = settings.dart_rate_limit

    click.echo("\nDART API Status")
    click.echo("=" * 40)
    click.echo(f"Daily limit:        {limit:,}")
    click.echo(f"Used today:         {count:,}")
    click.echo(f"Remaining:          {remaining:,}")
    click.echo(f"Usage:              {count/limit*100:.1f}%")

    # Check corp codes cache
    if CORP_CODES_CACHE_FILE.exists():
        cache_age = time.time() - CORP_CODES_CACHE_FILE.stat().st_mtime
        hours_old = cache_age / 3600
        click.echo(f"\nCorp codes cache:   {hours_old:.1f}h old")
    else:
        click.echo("\nCorp codes cache:   Not cached")

    click.echo("=" * 40)


@cli.command("reset-api-count")
@click.confirmation_option(prompt="Are you sure you want to reset the daily API count?")
def reset_api_count() -> None:
    """Reset daily API request count"""
    from kb_lockup.dart.api import reset_request_count
    reset_request_count()
    click.echo("Daily API request count has been reset.")


@cli.command("refresh-cache")
def refresh_cache() -> None:
    """Refresh the corporation codes cache from DART"""
    from kb_lockup.dart.api import DartAPI

    async def _refresh():
        async with DartAPI() as api:
            await api.load_corp_codes(force_refresh=True)
            click.echo("Corporation codes cache refreshed.")

    asyncio.run(_refresh())


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
            click.echo("\nStats:")
            click.echo(f"  Documents: {stats['documents_processed']}")
            click.echo(f"  Tables found: {stats['tables_found']}")
            click.echo(f"  API requests: {stats['api_requests']}")
            click.echo(f"  Errors: {stats['errors']}")

    asyncio.run(_extract())


@cli.command("fix-release-dates")
@click.option("--dry-run", is_flag=True, help="Show what would be updated without making changes")
def fix_release_dates(dry_run: bool) -> None:
    """Calculate missing release_date from listing_date + period_months"""
    from dateutil.relativedelta import relativedelta
    from kb_lockup.storage.database import Database
    from kb_lockup.analysis.market_data import get_market_data_service

    async def _fix():
        market_svc = get_market_data_service()

        if not market_svc.is_available():
            click.echo("Error: pykrx not installed. Run: pip install pykrx", err=True)
            raise click.Abort()

        async with Database() as db:
            # Get ALL lockups missing release_date (not just those with period_months)
            cursor = await db.conn.execute(
                "SELECT * FROM lockup_data WHERE release_date IS NULL AND stock_code IS NOT NULL"
            )
            rows = await cursor.fetchall()
            lockups = [db._row_to_lockup_data(row) for row in rows]

            if not lockups:
                click.echo("No lockups with missing release_date found.")
                return

            click.echo(f"Found {len(lockups)} lockups needing release_date")
            click.echo("-" * 60)

            # Group by stock_code to minimize API calls
            by_stock = {}
            for l in lockups:
                if l.stock_code not in by_stock:
                    by_stock[l.stock_code] = []
                by_stock[l.stock_code].append(l)

            updated = 0
            deleted = 0
            failed = 0

            for stock_code, entries in by_stock.items():
                company_name = entries[0].company_name

                # Fetch listing date from pykrx
                click.echo(f"\n{company_name} ({stock_code}): fetching listing date...")
                listing_date = market_svc.get_listing_date(stock_code)

                if not listing_date:
                    click.echo(f"  ⚠️  Could not get listing date")
                    failed += len(entries)
                    continue

                click.echo(f"  📅 Listing date: {listing_date}")

                # Update listing_date for the company
                if not dry_run:
                    await db.update_company_listing_date(stock_code, listing_date)

                # Update each entry
                for entry in entries:
                    if entry.lock_period_months:
                        # Use relativedelta for proper month arithmetic
                        release_date = listing_date + relativedelta(months=entry.lock_period_months)
                        click.echo(f"  → {entry.owner}: {entry.lock_period_months}개월 → {release_date}")
                    else:
                        # No period_months: use listing date as release date
                        release_date = listing_date
                        click.echo(f"  → {entry.owner}: (no period) → {release_date} (listing date)")

                    if not dry_run:
                        # Check if a record with this (company, owner, release_date) already exists
                        check_cursor = await db.conn.execute(
                            "SELECT id FROM lockup_data WHERE company_name = ? AND owner = ? AND release_date = ?",
                            (entry.company_name, entry.owner, release_date.isoformat())
                        )
                        existing = await check_cursor.fetchone()

                        if existing:
                            # Delete the current NULL record (duplicate)
                            click.echo(f"    ⚠️  Duplicate found, deleting NULL record")
                            await db.conn.execute("DELETE FROM lockup_data WHERE id = ?", (entry.id,))
                            await db.conn.commit()
                            deleted += 1
                        else:
                            await db.update_release_date(entry.id, release_date)
                            updated += 1
                    else:
                        updated += 1

            click.echo("\n" + "=" * 60)
            if dry_run:
                click.echo(f"DRY RUN: Would update {updated} records ({failed} failed)")
            else:
                click.echo(f"Updated {updated} records, deleted {deleted} duplicates ({failed} could not be fixed)")

    asyncio.run(_fix())


if __name__ == "__main__":
    cli()
