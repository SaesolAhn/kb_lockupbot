"""Standardize dates, amounts, and ratios from Korean formats"""

import re
from datetime import date, timedelta
from typing import Optional

from loguru import logger

from kb_lockup.core.constants import (
    DATE_PATTERNS,
    RELATIVE_DATE_PATTERNS,
    AMOUNT_PATTERNS,
    RATIO_PATTERNS,
)


class KoreanNormalizer:
    """Normalize Korean date formats and number expressions"""

    def normalize_date(
        self,
        raw_date: str,
        listing_date: Optional[date] = None,
    ) -> Optional[date]:
        """
        Parse various Korean date formats

        Args:
            raw_date: Raw date string
            listing_date: Listing date for relative calculations

        Returns:
            Parsed date or None
        """
        if not raw_date:
            return None

        raw_date = raw_date.strip()

        # Try absolute date patterns first
        result = self._parse_absolute_date(raw_date)
        if result:
            return result

        # Try relative date patterns (requires listing_date)
        if listing_date:
            result = self._parse_relative_date(raw_date, listing_date)
            if result:
                return result

        return None

    def _parse_absolute_date(self, raw_date: str) -> Optional[date]:
        """Parse absolute date formats"""
        for pattern in DATE_PATTERNS:
            match = re.search(pattern, raw_date)
            if match:
                try:
                    groups = match.groups()
                    year = int(groups[0])
                    month = int(groups[1])
                    day = int(groups[2])

                    # Validate ranges
                    if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                        return date(year, month, day)
                except (ValueError, IndexError):
                    continue

        return None

    def _parse_relative_date(
        self,
        raw_date: str,
        listing_date: date,
    ) -> Optional[date]:
        """Parse relative date expressions"""
        for pattern, unit in RELATIVE_DATE_PATTERNS:
            match = re.search(pattern, raw_date)
            if match:
                try:
                    amount = int(match.group(1))

                    if unit == "months":
                        # Approximate months as 30 days
                        return listing_date + timedelta(days=amount * 30)
                    elif unit == "years":
                        return listing_date + timedelta(days=amount * 365)
                except (ValueError, IndexError):
                    continue

        return None

    def parse_date(self, raw_date: str) -> Optional[date]:
        """Simple date parsing (alias for normalize_date without listing_date)"""
        return self.normalize_date(raw_date)

    def normalize_amount(self, raw_amount: str) -> Optional[int]:
        """
        Parse share amounts from Korean formats

        Examples:
            "1,234,567주" -> 1234567
            "123만주" -> 1230000
            "1,234천주" -> 1234000
        """
        if not raw_amount:
            return None

        raw_amount = str(raw_amount).strip()

        # Remove commas and spaces
        cleaned = raw_amount.replace(",", "").replace(" ", "")

        for pattern, multiplier in AMOUNT_PATTERNS:
            match = re.search(pattern, cleaned)
            if match:
                try:
                    value = float(match.group(1))
                    return int(value * multiplier)
                except (ValueError, IndexError):
                    continue

        # Try plain number
        try:
            # Remove non-numeric suffix
            number_match = re.match(r"([\d,]+)", raw_amount.replace(",", ""))
            if number_match:
                return int(number_match.group(1))
        except ValueError:
            pass

        return None

    def normalize_ratio(self, raw_ratio: str) -> Optional[float]:
        """
        Parse ownership ratios

        Examples:
            "12.34%" -> 12.34
            "12.34" -> 12.34
            "12.34퍼센트" -> 12.34
        """
        if not raw_ratio:
            return None

        raw_ratio = str(raw_ratio).strip()

        for pattern in RATIO_PATTERNS:
            match = re.search(pattern, raw_ratio)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    continue

        # Try plain number
        try:
            value = float(raw_ratio.replace(",", ""))
            # Sanity check for percentage range
            if 0 <= value <= 100:
                return value
        except ValueError:
            pass

        return None

    def normalize_period(self, raw_period: str) -> Optional[int]:
        """
        Parse lock period to months

        Examples:
            "6개월" -> 6
            "1년" -> 12
            "1년 6개월" -> 18
        """
        if not raw_period:
            return None

        raw_period = str(raw_period).strip()
        months = 0

        # Extract years
        year_match = re.search(r"(\d+)\s*년", raw_period)
        if year_match:
            months += int(year_match.group(1)) * 12

        # Extract months
        month_match = re.search(r"(\d+)\s*개월", raw_period)
        if month_match:
            months += int(month_match.group(1))

        return months if months > 0 else None
