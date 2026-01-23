"""Date parsing utilities for Korean formats"""

import re
from datetime import date, timedelta
from typing import Optional, Tuple


class DateParser:
    """Parse various Korean date formats"""

    # Date patterns
    PATTERNS = [
        # 2024년 1월 15일
        (r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", "%Y-%m-%d"),
        # 2024.01.15, 2024-01-15, 2024/01/15
        (r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", "%Y-%m-%d"),
        # 20240115
        (r"(\d{4})(\d{2})(\d{2})", "%Y-%m-%d"),
        # 24.01.15 (2-digit year)
        (r"(\d{2})[./-](\d{1,2})[./-](\d{1,2})", "%y-%m-%d"),
    ]

    # Relative date patterns
    RELATIVE_PATTERNS = [
        (r"상장일로부터\s*(\d+)\s*개월", "listing", "months"),
        (r"상장일로부터\s*(\d+)\s*년", "listing", "years"),
        (r"상장\s*후\s*(\d+)\s*개월", "listing", "months"),
        (r"상장\s*후\s*(\d+)\s*년", "listing", "years"),
        (r"(\d+)\s*개월\s*후", "current", "months"),
        (r"(\d+)\s*년\s*후", "current", "years"),
    ]

    @classmethod
    def parse(
        cls,
        text: str,
        reference_date: Optional[date] = None,
    ) -> Optional[date]:
        """
        Parse date from text

        Args:
            text: Date string to parse
            reference_date: Reference date for relative dates

        Returns:
            Parsed date or None
        """
        if not text:
            return None

        text = str(text).strip()

        # Try absolute patterns first
        result = cls._parse_absolute(text)
        if result:
            return result

        # Try relative patterns
        if reference_date:
            result = cls._parse_relative(text, reference_date)
            if result:
                return result

        return None

    @classmethod
    def _parse_absolute(cls, text: str) -> Optional[date]:
        """Parse absolute date formats"""
        for pattern, _ in cls.PATTERNS:
            match = re.search(pattern, text)
            if match:
                try:
                    groups = match.groups()
                    year = int(groups[0])
                    month = int(groups[1])
                    day = int(groups[2])

                    # Handle 2-digit year
                    if year < 100:
                        year += 2000 if year < 50 else 1900

                    # Validate
                    if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
                        return date(year, month, day)
                except (ValueError, IndexError):
                    continue

        return None

    @classmethod
    def _parse_relative(
        cls,
        text: str,
        reference_date: date,
    ) -> Optional[date]:
        """Parse relative date expressions"""
        for pattern, ref_type, unit in cls.RELATIVE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                try:
                    amount = int(match.group(1))

                    if unit == "months":
                        # Approximate months as 30 days
                        return reference_date + timedelta(days=amount * 30)
                    elif unit == "years":
                        return reference_date + timedelta(days=amount * 365)
                except (ValueError, IndexError):
                    continue

        return None

    @classmethod
    def parse_period(cls, text: str) -> Optional[int]:
        """
        Parse period to months

        Examples:
            "6개월" -> 6
            "1년" -> 12
            "1년 6개월" -> 18
        """
        if not text:
            return None

        text = str(text).strip()
        months = 0

        # Extract years
        year_match = re.search(r"(\d+)\s*년", text)
        if year_match:
            months += int(year_match.group(1)) * 12

        # Extract months
        month_match = re.search(r"(\d+)\s*개월", text)
        if month_match:
            months += int(month_match.group(1))

        return months if months > 0 else None

    @classmethod
    def calculate_release_date(
        cls,
        listing_date: date,
        period_months: int,
    ) -> date:
        """Calculate release date from listing date and period"""
        # Use approximate calculation (30 days per month)
        return listing_date + timedelta(days=period_months * 30)

    @classmethod
    def days_until(cls, target_date: date) -> int:
        """Calculate days until target date"""
        return (target_date - date.today()).days

    @classmethod
    def format_korean(cls, d: date) -> str:
        """Format date in Korean style"""
        return f"{d.year}년 {d.month}월 {d.day}일"

    @classmethod
    def parse_date_range(cls, text: str) -> Optional[Tuple[date, date]]:
        """
        Parse date range from text

        Examples:
            "2024.01.15 ~ 2024.06.15"
            "2024년 1월 15일 - 2024년 6월 15일"
        """
        # Split by common separators
        separators = ["~", "-", "부터", "까지"]
        for sep in separators:
            if sep in text:
                parts = text.split(sep, 1)
                if len(parts) == 2:
                    start = cls.parse(parts[0].strip())
                    end = cls.parse(parts[1].strip())
                    if start and end:
                        return (start, end)

        return None
