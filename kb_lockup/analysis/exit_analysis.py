"""Exit trading candidates analysis"""

from datetime import date
from typing import List, Optional

from loguru import logger

from kb_lockup.core.models import LockupData, ExitOpportunity
from kb_lockup.storage.database import Database


class ExitAnalyzer:
    """Analyze lockup data for exit trading opportunities"""

    def __init__(self, db: Database):
        self.db = db

    async def analyze_exit_candidates(
        self,
        days_ahead: int = 60,
        min_ratio: float = 1.0,
    ) -> List[ExitOpportunity]:
        """
        Find stocks where large holders may need to exit

        Args:
            days_ahead: Look for unlocks within this many days
            min_ratio: Minimum ownership percentage

        Returns:
            List of ExitOpportunity objects with liquidity analysis
        """
        unlocks = await self.db.get_upcoming_unlocks(
            days=days_ahead,
            min_ratio=min_ratio,
        )

        opportunities = []
        for lockup in unlocks:
            opp = await self._analyze_exit(lockup)
            if opp:
                opportunities.append(opp)

        # Sort by days to exit (harder exits first)
        opportunities.sort(
            key=lambda x: x.days_to_exit or float('inf'),
            reverse=True,
        )

        return opportunities

    async def _analyze_exit(self, lockup: LockupData) -> Optional[ExitOpportunity]:
        """Analyze exit difficulty for a lockup position"""
        if not lockup.release_date or not lockup.amount:
            return None

        days_until = (lockup.release_date - date.today()).days

        # TODO: Fetch real market data
        # For now, use placeholder values
        avg_daily_volume = None
        current_price = None
        days_to_exit = None

        # Calculate days to exit if we have volume data
        if avg_daily_volume and avg_daily_volume > 0:
            # Assume can trade 10% of daily volume without major impact
            tradeable_per_day = avg_daily_volume * 0.1
            days_to_exit = int(lockup.amount / tradeable_per_day)

        # Calculate value estimate if we have price
        value_estimate = None
        if current_price and lockup.amount:
            value_estimate = current_price * lockup.amount

        return ExitOpportunity(
            company_name=lockup.company_name,
            stock_code=lockup.stock_code,
            owner=lockup.owner,
            amount=lockup.amount,
            ratio=lockup.ratio or 0,
            release_date=lockup.release_date,
            days_until_unlock=days_until,
            current_price=current_price,
            value_estimate=value_estimate,
            avg_daily_volume=avg_daily_volume,
            days_to_exit=days_to_exit,
        )

    async def get_difficult_exits(
        self,
        min_days_to_exit: int = 30,
    ) -> List[ExitOpportunity]:
        """
        Find positions that will be difficult to exit

        Args:
            min_days_to_exit: Minimum estimated exit duration
        """
        all_opportunities = await self.analyze_exit_candidates(
            days_ahead=90,
            min_ratio=1.0,
        )

        # Filter to difficult exits
        difficult = [
            opp for opp in all_opportunities
            if opp.days_to_exit and opp.days_to_exit >= min_days_to_exit
        ]

        return difficult

    async def estimate_market_impact(
        self,
        stock_code: str,
        amount: int,
    ) -> dict:
        """
        Estimate market impact of selling a large position

        Args:
            stock_code: KRX stock code
            amount: Number of shares to sell

        Returns:
            Dict with impact analysis
        """
        # TODO: Implement actual market data lookup
        # This is a placeholder implementation
        return {
            "stock_code": stock_code,
            "amount": amount,
            "estimated_days": None,
            "estimated_impact_percent": None,
            "recommendation": "Market data not available",
        }
