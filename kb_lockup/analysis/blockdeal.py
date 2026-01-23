"""Blockdeal opportunity detection"""

from datetime import date
from typing import List, Optional

from loguru import logger

from kb_lockup.core.models import LockupData, ExitOpportunity
from kb_lockup.storage.database import Database
from kb_lockup.analysis.market_data import get_market_data_service, MarketDataService


class BlockdealAnalyzer:
    """Analyze lockup data for blockdeal opportunities"""

    def __init__(self, db: Database, market_data: Optional[MarketDataService] = None):
        self.db = db
        self.market_data = market_data or get_market_data_service()

    async def find_opportunities(
        self,
        days_ahead: int = 30,
        min_ratio: float = 1.0,
        min_amount: Optional[int] = None,
    ) -> List[ExitOpportunity]:
        """
        Find potential blockdeal opportunities

        Args:
            days_ahead: Look for unlocks within this many days
            min_ratio: Minimum ownership percentage
            min_amount: Minimum share count

        Returns:
            List of ExitOpportunity objects sorted by opportunity score
        """
        # Get upcoming unlocks
        unlocks = await self.db.get_upcoming_unlocks(
            days=days_ahead,
            min_ratio=min_ratio,
        )

        opportunities = []
        for lockup in unlocks:
            # Filter by amount if specified
            if min_amount and lockup.amount and lockup.amount < min_amount:
                continue

            opp = self._create_opportunity(lockup)
            if opp:
                opportunities.append(opp)

        # Sort by opportunity score
        opportunities.sort(key=lambda x: x.opportunity_score or 0, reverse=True)

        logger.info(f"Found {len(opportunities)} blockdeal opportunities")
        return opportunities

    def _create_opportunity(self, lockup: LockupData) -> Optional[ExitOpportunity]:
        """Create ExitOpportunity from lockup data"""
        if not lockup.release_date:
            return None

        days_until = (lockup.release_date - date.today()).days

        # Fetch market data if available
        current_price = None
        value_estimate = None
        avg_daily_volume = None
        days_to_exit = None

        if lockup.stock_code and self.market_data.is_available():
            try:
                market_info = self.market_data.get_stock_info(lockup.stock_code)
                if market_info:
                    current_price = market_info.get("current_price")
                    avg_daily_volume = market_info.get("avg_volume_20d")

                    if current_price and lockup.amount:
                        value_estimate = current_price * lockup.amount

                    if avg_daily_volume and lockup.amount:
                        days_to_exit = self.market_data.estimate_exit_days(
                            lockup.stock_code,
                            lockup.amount,
                        )
            except Exception as e:
                logger.debug(f"Could not fetch market data for {lockup.stock_code}: {e}")

        # Calculate opportunity score
        # Higher score = larger position unlocking sooner
        score = self._calculate_score(
            ratio=lockup.ratio,
            amount=lockup.amount,
            days_until=days_until,
            value_estimate=value_estimate,
        )

        return ExitOpportunity(
            company_name=lockup.company_name,
            stock_code=lockup.stock_code,
            owner=lockup.owner,
            amount=lockup.amount or 0,
            ratio=lockup.ratio or 0,
            release_date=lockup.release_date,
            days_until_unlock=days_until,
            current_price=current_price,
            value_estimate=value_estimate,
            avg_daily_volume=avg_daily_volume,
            days_to_exit=days_to_exit,
            opportunity_score=score,
        )

    def _calculate_score(
        self,
        ratio: Optional[float],
        amount: Optional[int],
        days_until: int,
        value_estimate: Optional[float] = None,
    ) -> float:
        """
        Calculate opportunity score

        Factors:
        - Larger ownership % = higher score
        - More shares = higher score
        - Sooner release = higher score
        - Higher value = higher score (if market data available)
        """
        import math
        score = 0.0

        # Ratio component (0-40 points)
        if ratio:
            score += min(ratio * 4, 40)

        # Amount component (0-20 points, log scale)
        if amount:
            score += min(math.log10(amount + 1) * 3, 20)

        # Value component (0-20 points, log scale) - bonus if market data available
        if value_estimate and value_estimate > 0:
            # Score based on value in billions KRW
            value_billions = value_estimate / 1_000_000_000
            score += min(math.log10(value_billions + 1) * 10, 20)

        # Timing component (0-20 points, inverse of days)
        if days_until > 0:
            score += max(20 - days_until * 0.5, 0)

        return round(score, 2)

    async def get_large_positions(
        self,
        min_ratio: float = 5.0,
    ) -> List[LockupData]:
        """
        Get all large lockup positions regardless of release date

        Args:
            min_ratio: Minimum ownership percentage (default 5%)
        """
        # Get all upcoming unlocks with high ratio
        unlocks = await self.db.get_upcoming_unlocks(
            days=365,  # Look ahead 1 year
            min_ratio=min_ratio,
        )

        return unlocks
