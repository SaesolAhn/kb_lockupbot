"""Korean stock market data service using pykrx"""

from datetime import date, timedelta
from typing import Optional, Dict, Any

from loguru import logger

try:
    from pykrx import stock
    PYKRX_AVAILABLE = True
except ImportError:
    PYKRX_AVAILABLE = False
    logger.warning("pykrx not installed. Run: pip install pykrx")


class MarketDataService:
    """
    Fetch Korean stock market data from KRX.

    Uses pykrx library for free access to:
    - Current/historical prices
    - Trading volume
    - Market cap
    """

    def __init__(self, cache_ttl_minutes: int = 30):
        self.cache_ttl = cache_ttl_minutes
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_time: Dict[str, date] = {}

    def is_available(self) -> bool:
        """Check if market data service is available"""
        return PYKRX_AVAILABLE

    def get_stock_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        Get current stock information including price and volume.

        Args:
            stock_code: 6-digit KRX stock code (e.g., "005930" for Samsung)

        Returns:
            Dict with: current_price, avg_volume_20d, market_cap, name
        """
        if not PYKRX_AVAILABLE:
            logger.debug("pykrx not available")
            return None

        if not stock_code:
            return None

        # Normalize stock code
        stock_code = stock_code.strip().zfill(6)

        # Check cache
        cached = self._get_cached(stock_code)
        if cached:
            return cached

        try:
            # Get recent trading data (last 30 days)
            end_date = date.today()
            start_date = end_date - timedelta(days=45)  # Extra days for holidays

            df = stock.get_market_ohlcv(
                start_date.strftime("%Y%m%d"),
                end_date.strftime("%Y%m%d"),
                stock_code,
            )

            if df.empty:
                logger.warning(f"No market data found for {stock_code}")
                return None

            # Get latest data
            latest = df.iloc[-1]
            current_price = int(latest["종가"])

            # Calculate 20-day average volume
            recent_volume = df["거래량"].tail(20)
            avg_volume_20d = int(recent_volume.mean()) if len(recent_volume) > 0 else 0

            # Get stock name
            try:
                stock_name = stock.get_market_ticker_name(stock_code)
            except Exception:
                stock_name = None

            # Get market cap
            try:
                market_cap_df = stock.get_market_cap(
                    end_date.strftime("%Y%m%d"),
                    end_date.strftime("%Y%m%d"),
                    stock_code,
                )
                market_cap = int(market_cap_df.iloc[0]["시가총액"]) if not market_cap_df.empty else None
            except Exception:
                market_cap = None

            result = {
                "stock_code": stock_code,
                "name": stock_name,
                "current_price": current_price,
                "avg_volume_20d": avg_volume_20d,
                "market_cap": market_cap,
                "last_updated": end_date.isoformat(),
            }

            # Cache the result
            self._set_cache(stock_code, result)

            return result

        except Exception as e:
            logger.error(f"Failed to fetch market data for {stock_code}: {e}")
            return None

    def get_current_price(self, stock_code: str) -> Optional[float]:
        """Get current stock price"""
        info = self.get_stock_info(stock_code)
        return info["current_price"] if info else None

    def get_avg_volume(self, stock_code: str, days: int = 20) -> Optional[int]:
        """Get average daily trading volume"""
        info = self.get_stock_info(stock_code)
        return info["avg_volume_20d"] if info else None

    def estimate_exit_days(
        self,
        stock_code: str,
        shares_to_sell: int,
        max_daily_participation: float = 0.1,
    ) -> Optional[int]:
        """
        Estimate how many days it would take to exit a position.

        Args:
            stock_code: KRX stock code
            shares_to_sell: Number of shares to sell
            max_daily_participation: Max % of daily volume to trade (default 10%)

        Returns:
            Estimated days to exit, or None if data unavailable
        """
        avg_volume = self.get_avg_volume(stock_code)
        if not avg_volume or avg_volume == 0:
            return None

        # Calculate tradeable shares per day
        tradeable_per_day = int(avg_volume * max_daily_participation)
        if tradeable_per_day == 0:
            return None

        # Calculate days needed
        days = (shares_to_sell + tradeable_per_day - 1) // tradeable_per_day
        return days

    def estimate_value(
        self,
        stock_code: str,
        shares: int,
    ) -> Optional[float]:
        """
        Estimate value of a position at current price.

        Args:
            stock_code: KRX stock code
            shares: Number of shares

        Returns:
            Estimated value in KRW
        """
        price = self.get_current_price(stock_code)
        if price is None:
            return None
        return price * shares

    def _get_cached(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """Get cached data if still valid"""
        if stock_code not in self._cache:
            return None

        cache_date = self._cache_time.get(stock_code)
        if cache_date and cache_date == date.today():
            return self._cache[stock_code]

        return None

    def _set_cache(self, stock_code: str, data: Dict[str, Any]) -> None:
        """Cache data"""
        self._cache[stock_code] = data
        self._cache_time[stock_code] = date.today()

    def clear_cache(self) -> None:
        """Clear all cached data"""
        self._cache.clear()
        self._cache_time.clear()


    def get_listing_date(self, stock_code: str) -> Optional[date]:
        """
        Get the listing (first trading) date for a stock.

        Args:
            stock_code: 6-digit KRX stock code

        Returns:
            First trading date or None if unavailable
        """
        if not PYKRX_AVAILABLE:
            return None

        stock_code = stock_code.strip().zfill(6)

        try:
            # Get historical data going back far enough to find listing
            df = stock.get_market_ohlcv(
                "19900101",  # Start from 1990
                date.today().strftime("%Y%m%d"),
                stock_code,
            )

            if df.empty:
                return None

            # First date in the dataframe is the listing date
            first_date = df.index[0]
            return first_date.date() if hasattr(first_date, 'date') else first_date

        except Exception as e:
            logger.warning(f"Failed to get listing date for {stock_code}: {e}")
            return None


# Singleton instance
_market_data_service: Optional[MarketDataService] = None


def get_market_data_service() -> MarketDataService:
    """Get or create the market data service singleton"""
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
