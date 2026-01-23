"""Exit trading candidates analysis"""

from datetime import date
from typing import List, Optional

from loguru import logger

from kb_lockup.core.models import LockupData, ExitOpportunity
from kb_lockup.storage.database import Database
from kb_lockup.analysis.market_data import get_market_data_service, MarketDataService


class ExitAnalyzer:
    """Analyze lockup data for exit trading opportunities"""

    def __init__(self, db: Database, market_data: Optional[MarketDataService] = None):
        self.db = db
        self.market_data = market_data or get_market_data_service()

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

        # Fetch real market data if stock code is available
        avg_daily_volume = None
        current_price = None
        days_to_exit = None
        value_estimate = None

        if lockup.stock_code and self.market_data.is_available():
            try:
                # Get market data
                market_info = self.market_data.get_stock_info(lockup.stock_code)

                if market_info:
                    current_price = market_info.get("current_price")
                    avg_daily_volume = market_info.get("avg_volume_20d")

                    # Calculate days to exit (assuming 10% daily participation)
                    if avg_daily_volume and avg_daily_volume > 0:
                        days_to_exit = self.market_data.estimate_exit_days(
                            lockup.stock_code,
                            lockup.amount,
                            max_daily_participation=0.1,
                        )

                    # Calculate value estimate
                    if current_price:
                        value_estimate = self.market_data.estimate_value(
                            lockup.stock_code,
                            lockup.amount,
                        )

                    logger.debug(
                        f"Market data for {lockup.stock_code}: "
                        f"price={current_price:,}, vol={avg_daily_volume:,}, "
                        f"exit_days={days_to_exit}"
                    )

            except Exception as e:
                logger.warning(f"Failed to fetch market data for {lockup.stock_code}: {e}")

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
        result = {
            "stock_code": stock_code,
            "amount": amount,
            "estimated_days": None,
            "estimated_impact_percent": None,
            "value_estimate": None,
            "avg_daily_volume": None,
            "recommendation": "Market data not available",
        }

        if not self.market_data.is_available():
            return result

        try:
            market_info = self.market_data.get_stock_info(stock_code)

            if not market_info:
                return result

            avg_volume = market_info.get("avg_volume_20d", 0)
            current_price = market_info.get("current_price")

            result["avg_daily_volume"] = avg_volume

            # Calculate estimated exit days
            if avg_volume and avg_volume > 0:
                days_to_exit = self.market_data.estimate_exit_days(
                    stock_code, amount, max_daily_participation=0.1
                )
                result["estimated_days"] = days_to_exit

                # Calculate impact as % of daily volume
                daily_impact = (amount / avg_volume) * 100 if avg_volume > 0 else None
                result["estimated_impact_percent"] = round(daily_impact, 2) if daily_impact else None

            # Calculate value estimate
            if current_price:
                result["value_estimate"] = current_price * amount

            # Generate recommendation
            if result["estimated_days"]:
                if result["estimated_days"] <= 5:
                    result["recommendation"] = "쉬운 청산 - 일주일 내 완료 가능"
                elif result["estimated_days"] <= 20:
                    result["recommendation"] = "보통 - 약 1개월 내 청산 가능"
                elif result["estimated_days"] <= 60:
                    result["recommendation"] = "어려움 - 2개월 이상 소요 예상"
                else:
                    result["recommendation"] = "매우 어려움 - 장기간 소요, 블록딜 검토 권장"

        except Exception as e:
            logger.error(f"Failed to estimate market impact for {stock_code}: {e}")

        return result
