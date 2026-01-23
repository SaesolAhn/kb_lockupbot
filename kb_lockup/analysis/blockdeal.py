"""Blockdeal opportunity detection"""

from datetime import date, timedelta
from typing import List, Optional

from loguru import logger

from kb_lockup.core.models import LockupData, ExitOpportunity
from kb_lockup.storage.database import Database


class BlockdealAnalyzer:
    """Analyze lockup data for blockdeal opportunities"""

    def __init__(self, db: Database):
        self.db = db

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

        # Calculate opportunity score
        # Higher score = larger position unlocking sooner
        score = self._calculate_score(
            ratio=lockup.ratio,
            amount=lockup.amount,
            days_until=days_until,
        )

        return ExitOpportunity(
            company_name=lockup.company_name,
            stock_code=lockup.stock_code,
            owner=lockup.owner,
            amount=lockup.amount or 0,
            ratio=lockup.ratio or 0,
            release_date=lockup.release_date,
            days_until_unlock=days_until,
            opportunity_score=score,
        )

    def _calculate_score(
        self,
        ratio: Optional[float],
        amount: Optional[int],
        days_until: int,
    ) -> float:
        """
        Calculate opportunity score

        Factors:
        - Larger ownership % = higher score
        - More shares = higher score
        - Sooner release = higher score
        """
        score = 0.0

        # Ratio component (0-50 points)
        if ratio:
            score += min(ratio * 5, 50)

        # Amount component (0-30 points, log scale)
        if amount:
            import math
            score += min(math.log10(amount + 1) * 5, 30)

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
