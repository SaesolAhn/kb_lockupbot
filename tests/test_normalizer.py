"""Tests for Korean date/amount normalizer"""

import pytest
from datetime import date

from kb_lockup.extraction.normalizer import KoreanNormalizer


class TestDateNormalization:
    """Test date parsing"""

    def setup_method(self):
        self.normalizer = KoreanNormalizer()

    def test_korean_date_format(self):
        """Test 2024년 1월 15일 format"""
        result = self.normalizer.normalize_date("2024년 1월 15일")
        assert result == date(2024, 1, 15)

    def test_korean_date_with_spaces(self):
        """Test date with extra spaces"""
        result = self.normalizer.normalize_date("2024년  1월  15일")
        assert result == date(2024, 1, 15)

    def test_dot_separated_date(self):
        """Test 2024.01.15 format"""
        result = self.normalizer.normalize_date("2024.01.15")
        assert result == date(2024, 1, 15)

    def test_dash_separated_date(self):
        """Test 2024-01-15 format"""
        result = self.normalizer.normalize_date("2024-01-15")
        assert result == date(2024, 1, 15)

    def test_slash_separated_date(self):
        """Test 2024/01/15 format"""
        result = self.normalizer.normalize_date("2024/01/15")
        assert result == date(2024, 1, 15)

    def test_relative_date_months(self):
        """Test relative date with months"""
        listing = date(2024, 1, 15)
        result = self.normalizer.normalize_date(
            "상장일로부터 6개월",
            listing_date=listing,
        )
        # 6 months ≈ 180 days
        assert result == date(2024, 7, 14)

    def test_relative_date_years(self):
        """Test relative date with years"""
        listing = date(2024, 1, 15)
        result = self.normalizer.normalize_date(
            "상장일로부터 1년",
            listing_date=listing,
        )
        # 1 year ≈ 365 days
        assert result == date(2025, 1, 15)

    def test_invalid_date(self):
        """Test invalid date string"""
        result = self.normalizer.normalize_date("invalid")
        assert result is None

    def test_empty_date(self):
        """Test empty string"""
        result = self.normalizer.normalize_date("")
        assert result is None


class TestAmountNormalization:
    """Test share amount parsing"""

    def setup_method(self):
        self.normalizer = KoreanNormalizer()

    def test_amount_with_comma(self):
        """Test 1,234,567주 format"""
        result = self.normalizer.normalize_amount("1,234,567주")
        assert result == 1234567

    def test_amount_man_unit(self):
        """Test 123만주 format"""
        result = self.normalizer.normalize_amount("123만주")
        assert result == 1230000

    def test_amount_decimal_man(self):
        """Test 12.5만주 format"""
        result = self.normalizer.normalize_amount("12.5만주")
        assert result == 125000

    def test_amount_cheon_unit(self):
        """Test 1,234천주 format"""
        result = self.normalizer.normalize_amount("1,234천주")
        assert result == 1234000

    def test_plain_number(self):
        """Test plain number"""
        result = self.normalizer.normalize_amount("1000000")
        assert result == 1000000

    def test_invalid_amount(self):
        """Test invalid amount"""
        result = self.normalizer.normalize_amount("invalid")
        assert result is None


class TestRatioNormalization:
    """Test ownership ratio parsing"""

    def setup_method(self):
        self.normalizer = KoreanNormalizer()

    def test_ratio_with_percent(self):
        """Test 12.34% format"""
        result = self.normalizer.normalize_ratio("12.34%")
        assert result == 12.34

    def test_ratio_korean_percent(self):
        """Test 12.34퍼센트 format"""
        result = self.normalizer.normalize_ratio("12.34퍼센트")
        assert result == 12.34

    def test_ratio_plain_number(self):
        """Test plain number"""
        result = self.normalizer.normalize_ratio("12.34")
        assert result == 12.34

    def test_invalid_ratio(self):
        """Test invalid ratio"""
        result = self.normalizer.normalize_ratio("invalid")
        assert result is None


class TestPeriodNormalization:
    """Test lock period parsing"""

    def setup_method(self):
        self.normalizer = KoreanNormalizer()

    def test_period_months(self):
        """Test 6개월 format"""
        result = self.normalizer.normalize_period("6개월")
        assert result == 6

    def test_period_year(self):
        """Test 1년 format"""
        result = self.normalizer.normalize_period("1년")
        assert result == 12

    def test_period_year_and_months(self):
        """Test 1년 6개월 format"""
        result = self.normalizer.normalize_period("1년 6개월")
        assert result == 18

    def test_invalid_period(self):
        """Test invalid period"""
        result = self.normalizer.normalize_period("invalid")
        assert result is None
