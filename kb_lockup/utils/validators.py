"""Input validation utilities"""

import re
from datetime import date
from typing import Optional, Tuple

from kb_lockup.core.exceptions import ValidationError


class InputValidator:
    """Validate user inputs and data"""

    # Stock code pattern (6 digits)
    STOCK_CODE_PATTERN = re.compile(r"^\d{6}$")

    # Corp code pattern (8 digits)
    CORP_CODE_PATTERN = re.compile(r"^\d{8}$")

    # DART receipt number pattern
    RCEPT_NO_PATTERN = re.compile(r"^\d{14}$")

    @classmethod
    def validate_stock_code(cls, code: str) -> str:
        """
        Validate and normalize stock code

        Args:
            code: Stock code to validate

        Returns:
            Normalized 6-digit stock code

        Raises:
            ValidationError: If code is invalid
        """
        if not code:
            raise ValidationError("Stock code is required", field="stock_code")

        code = str(code).strip()

        # Pad with leading zeros if needed
        if code.isdigit() and len(code) < 6:
            code = code.zfill(6)

        if not cls.STOCK_CODE_PATTERN.match(code):
            raise ValidationError(
                f"Invalid stock code: {code}. Must be 6 digits.",
                field="stock_code",
                value=code,
            )

        return code

    @classmethod
    def validate_corp_code(cls, code: str) -> str:
        """Validate DART corporation code"""
        if not code:
            raise ValidationError("Corp code is required", field="corp_code")

        code = str(code).strip()

        if not cls.CORP_CODE_PATTERN.match(code):
            raise ValidationError(
                f"Invalid corp code: {code}. Must be 8 digits.",
                field="corp_code",
                value=code,
            )

        return code

    @classmethod
    def validate_rcept_no(cls, rcept_no: str) -> str:
        """Validate DART receipt number"""
        if not rcept_no:
            raise ValidationError("Receipt number is required", field="rcept_no")

        rcept_no = str(rcept_no).strip()

        if not cls.RCEPT_NO_PATTERN.match(rcept_no):
            raise ValidationError(
                f"Invalid receipt number: {rcept_no}. Must be 14 digits.",
                field="rcept_no",
                value=rcept_no,
            )

        return rcept_no

    @classmethod
    def validate_date(
        cls,
        value: str,
        field_name: str = "date",
    ) -> date:
        """Validate and parse date string"""
        from kb_lockup.utils.date_utils import DateParser

        if not value:
            raise ValidationError(f"{field_name} is required", field=field_name)

        parsed = DateParser.parse(str(value))
        if not parsed:
            raise ValidationError(
                f"Invalid date format: {value}",
                field=field_name,
                value=value,
            )

        return parsed

    @classmethod
    def validate_date_range(
        cls,
        start: str,
        end: str,
    ) -> Tuple[date, date]:
        """Validate date range"""
        start_date = cls.validate_date(start, "start_date")
        end_date = cls.validate_date(end, "end_date")

        if start_date > end_date:
            raise ValidationError(
                "Start date must be before end date",
                field="date_range",
            )

        return start_date, end_date

    @classmethod
    def validate_ratio(
        cls,
        value: float,
        field_name: str = "ratio",
    ) -> float:
        """Validate ownership ratio"""
        if value is None:
            raise ValidationError(f"{field_name} is required", field=field_name)

        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValidationError(
                f"Invalid ratio: {value}. Must be a number.",
                field=field_name,
                value=str(value),
            )

        if not 0 <= value <= 100:
            raise ValidationError(
                f"Ratio must be between 0 and 100: {value}",
                field=field_name,
                value=str(value),
            )

        return value

    @classmethod
    def validate_amount(
        cls,
        value: int,
        field_name: str = "amount",
    ) -> int:
        """Validate share amount"""
        if value is None:
            raise ValidationError(f"{field_name} is required", field=field_name)

        try:
            value = int(value)
        except (ValueError, TypeError):
            raise ValidationError(
                f"Invalid amount: {value}. Must be an integer.",
                field=field_name,
                value=str(value),
            )

        if value < 0:
            raise ValidationError(
                f"Amount must be non-negative: {value}",
                field=field_name,
                value=str(value),
            )

        return value

    @classmethod
    def validate_company_name(cls, name: str) -> str:
        """Validate company name"""
        if not name:
            raise ValidationError("Company name is required", field="company_name")

        name = str(name).strip()

        if len(name) < 2:
            raise ValidationError(
                "Company name must be at least 2 characters",
                field="company_name",
                value=name,
            )

        if len(name) > 100:
            raise ValidationError(
                "Company name must be at most 100 characters",
                field="company_name",
                value=name,
            )

        return name

    @classmethod
    def is_valid_stock_code(cls, code: str) -> bool:
        """Check if stock code is valid without raising exception"""
        try:
            cls.validate_stock_code(code)
            return True
        except ValidationError:
            return False

    @classmethod
    def sanitize_search_query(cls, query: str) -> str:
        """Sanitize search query for database"""
        if not query:
            return ""

        # Remove potentially dangerous characters
        query = re.sub(r"[;'\"\\\x00]", "", query)

        # Normalize whitespace
        query = " ".join(query.split())

        return query.strip()
