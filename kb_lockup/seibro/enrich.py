from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Any
import logging
from pykrx import stock
import pandas as pd

logger = logging.getLogger(__name__)

class Enricher:
    """
    Enriches unstaking data with market prices and calculated values.
    """
    
    def __init__(self):
        self._price_cache: Dict[str, float] = {}
        self._price_cache_date: Optional[date] = None

    def _get_latest_business_day(self) -> date:
        """Finds the most recent business day (naive approach)."""
        d = datetime.now().date()
        # If weekend, go back
        while d.weekday() > 4:  # Sat=5, Sun=6
            d -= timedelta(days=1)
        return d

    def _refresh_price_cache(self):
        """
        Fetches the latest closing prices for all stocks in KOSPI and KOSDAQ.
        This avoids N requests for N stocks.
        """
        target_date = self._get_latest_business_day()
        target_date_str = target_date.strftime("%Y%m%d")
        
        if self._price_cache_date == target_date and self._price_cache:
            return

        logger.info(f"Refreshing price cache for {target_date_str}...")
        self._price_cache = {}
        
        try:
            # Fetch KOSPI
            df_kospi = stock.get_market_ohlcv(target_date_str, market="KOSPI")
            if not df_kospi.empty:
                # index is ticker (short code), '종가' is close
                for ticker, row in df_kospi.iterrows():
                    self._price_cache[str(ticker)] = float(row['종가'])
                    
            # Fetch KOSDAQ
            df_kosdaq = stock.get_market_ohlcv(target_date_str, market="KOSDAQ")
            if not df_kosdaq.empty:
                for ticker, row in df_kosdaq.iterrows():
                    self._price_cache[str(ticker)] = float(row['종가'])
                    
            # Fetch KONEX (optional but good for completeness as we handle 'All' markets)
            df_konex = stock.get_market_ohlcv(target_date_str, market="KONEX")
            if not df_konex.empty:
                for ticker, row in df_konex.iterrows():
                    self._price_cache[str(ticker)] = float(row['종가'])

            self._price_cache_date = target_date
            logger.info(f"Price cache refreshed. Parsed {len(self._price_cache)} tickers.")
            
        except Exception as e:
            logger.error(f"Failed to fetch market prices via pykrx: {e}")
            # Do not clear cache if fail, stick with what we have or empty
            pass

    def enrich_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enriches a list of dictionaries (parsed rows) with:
        - stake_portion_pct
        - stock_current_price_krw
        - current_stake_value_million_krw
        """
        # Ensure cache is fresh
        self._refresh_price_cache()
        
        enriched = []
        for row in rows:
            # Copy to avoid mutating original if needed, or just mutate
            item = row.copy()
            
            # 1. Stake Portion
            total_shares = item.get("total_shares")
            return_shares = item.get("return_shares") or 0
            
            if total_shares and total_shares > 0:
                item["stake_portion_pct"] = round((return_shares / total_shares) * 100, 2)
            else:
                item["stake_portion_pct"] = None
                
            # 2. Price and Value
            short_code = item.get("short_code")
            price = self._price_cache.get(short_code)
            
            # Try looking up without A prefix if present or vice versa if needed
            # pykrx returns standard 6 digit codes usually.
            
            if price is not None:
                item["stock_current_price_krw"] = price
                item["current_stake_value_million_krw"] = round((return_shares * price) / 1_000_000, 2)
            else:
                item["stock_current_price_krw"] = None
                item["current_stake_value_million_krw"] = None
                
            enriched.append(item)
            
        return enriched
