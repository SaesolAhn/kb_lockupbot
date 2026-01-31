import argparse
import logging
import time
from datetime import datetime, date, timedelta
from typing import List, Optional

from kb_lockup.seibro.seibro_client import SeibroClient
from kb_lockup.seibro import parser
from kb_lockup.seibro.enrich import Enricher
from kb_lockup.seibro.db_utils import upsert_unstaking_rows
from kb_lockup.config import settings

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class UnstakingCrawler:
    def __init__(self):
        self.client = SeibroClient()
        self.enricher = Enricher()
        self.target_markets = ["유가증권시장", "코스닥시장"]
        
    def crawl_unstaking_period(self, start_date: date, end_date: date):
        """
        Crawls unstaking data for the given period.
        """
        logger.info(f"Starting crawl for period: {start_date} ~ {end_date}")
        
        all_rows = []
        
        # We iterate over target markets to use server-side filtering as much as possible
        for market in self.target_markets:
            logger.info(f"Fetching data for market: {market}")
            market_rows = self._fetch_market_data(start_date, end_date, market)
            all_rows.extend(market_rows)
            
        logger.info(f"Fetched total {len(all_rows)} rows before enrichment.")
        
        # Enrich with price info
        if all_rows:
            logger.info("Enriching rows with market data...")
            enriched_rows = self.enricher.enrich_rows(all_rows)
            
            # Save to DB
            logger.info("Upserting rows into database...")
            upsert_unstaking_rows(enriched_rows)
            logger.info("Crawl complete.")
        else:
            logger.info("No rows found for this period.")

    def _fetch_market_data(self, start_date: date, end_date: date, market: str) -> List[dict]:
        rows = []
        page = 1
        
        while True:
            try:
                logger.debug(f"Fetching page {page} for {market}...")
                response_content = self.client.fetch_protection_returns(
                    start_date=start_date,
                    end_date=end_date,
                    market_type=market,
                    page=page
                )
                
                parsed_rows = parser.parse_protection_table(response_content)
                
                if not parsed_rows:
                    logger.debug("No rows returned (end of pages).")
                    break
                
                # Filter specifically for the requested market (double check)
                # The server might return everything if parameter is ignored, so we filter client-side too.
                filtered_batch = [
                    r for r in parsed_rows 
                    if r.get("market_type") == market
                ]
                
                # If we got rows but none matched market (rare if server filters correctly), we still continue?
                # Actually, relying on server filter is efficient.
                # Let's save what we parsed if it matches.
                rows.extend(filtered_batch)
                
                logger.info(f"Page {page}: Found {len(parsed_rows)} rows ({len(filtered_batch)} matched).")
                
                # Pagination termination
                # If we got fewer than typical page size (30), it's likely last page
                if len(parsed_rows) < 30:
                    break
                    
                page += 1
                time.sleep(0.5) # Polite delay
                
            except Exception as e:
                logger.error(f"Error fetching page {page} for {market}: {e}")
                # Retry logic could go here
                break
                
        return rows

    def update_today_unstaking(self):
        """
        Updates unstaking schedule for a window around today.
        Default: Today to Today+7 days to ensure upcoming are captured/updated.
        """
        today = date.today()
        end_window = today + timedelta(days=7)
        logger.info(f"Running daily update for {today} to {end_window}")
        self.crawl_unstaking_period(today, end_window)

    def backfill_history(self, start_date: date, end_date: date, step_days: int = 30):
        """
        Backfills history in chunks.
        """
        current_start = start_date
        while current_start <= end_date:
            current_end = min(current_start + timedelta(days=step_days), end_date)
            logger.info(f"Backfilling chunk: {current_start} ~ {current_end}")
            
            self.crawl_unstaking_period(current_start, current_end)
            
            current_start = current_end + timedelta(days=1)
            time.sleep(1)

def main():
    parser = argparse.ArgumentParser(description="SEIBro Unstaking Schedule Crawler")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # run_daily
    subparsers.add_parser("run_daily", help="Run daily update")
    
    # backfill
    backfill_parser = subparsers.add_parser("backfill", help="Backfill historical data")
    backfill_parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    backfill_parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    backfill_parser.add_argument("--step", type=int, default=30, help="Step size in days")
    
    # manual
    manual_parser = subparsers.add_parser("manual", help="Manual run for specific period")
    manual_parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    manual_parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")

    args = parser.parse_args()
    
    crawler = UnstakingCrawler()
    
    if args.command == "run_daily":
        crawler.update_today_unstaking()
        
    elif args.command == "backfill":
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
        crawler.backfill_history(start, end, args.step)
        
    elif args.command == "manual":
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
        crawler.crawl_unstaking_period(start, end)

if __name__ == "__main__":
    main()
