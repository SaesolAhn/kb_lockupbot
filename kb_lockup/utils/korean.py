"""Korean text processing utilities"""

import re
from typing import Optional


class KoreanTextProcessor:
    """Process Korean text for extraction and normalization"""

    # Korean character ranges
    HANGUL_START = 0xAC00
    HANGUL_END = 0xD7A3
    JAMO_START = 0x1100
    JAMO_END = 0x11FF

    @staticmethod
    def contains_korean(text: str) -> bool:
        """Check if text contains Korean characters"""
        for char in text:
            code = ord(char)
            if (KoreanTextProcessor.HANGUL_START <= code <= KoreanTextProcessor.HANGUL_END or
                KoreanTextProcessor.JAMO_START <= code <= KoreanTextProcessor.JAMO_END):
                return True
        return False

    @staticmethod
    def extract_korean(text: str) -> str:
        """Extract only Korean characters from text"""
        result = []
        for char in text:
            code = ord(char)
            if (KoreanTextProcessor.HANGUL_START <= code <= KoreanTextProcessor.HANGUL_END or
                KoreanTextProcessor.JAMO_START <= code <= KoreanTextProcessor.JAMO_END or
                char.isspace()):
                result.append(char)
        return "".join(result).strip()

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """Normalize whitespace in text"""
        # Replace multiple spaces/newlines with single space
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def remove_parentheses_content(text: str) -> str:
        """Remove content within parentheses"""
        # Remove (내용), [내용], 【내용】
        text = re.sub(r"\([^)]*\)", "", text)
        text = re.sub(r"\[[^\]]*\]", "", text)
        text = re.sub(r"【[^】]*】", "", text)
        return text.strip()

    @staticmethod
    def extract_company_name(text: str) -> Optional[str]:
        """Extract company name from text"""
        # Common patterns: 주식회사 XXX, XXX 주식회사, (주)XXX
        patterns = [
            r"주식회사\s*([가-힣A-Za-z0-9]+)",
            r"([가-힣A-Za-z0-9]+)\s*주식회사",
            r"\(주\)\s*([가-힣A-Za-z0-9]+)",
            r"([가-힣A-Za-z0-9]+)\s*\(주\)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        return None

    @staticmethod
    def extract_person_name(text: str) -> Optional[str]:
        """Extract Korean person name from text"""
        # Korean names are typically 2-4 characters
        match = re.search(r"([가-힣]{2,4})", text)
        if match:
            name = match.group(1)
            # Filter out common non-name words
            non_names = {"주식회사", "대표이사", "이사회", "감사위원"}
            if name not in non_names:
                return name
        return None

    @staticmethod
    def normalize_number_text(text: str) -> str:
        """Convert Korean number expressions to digits"""
        # Map Korean digits to numbers
        korean_digits = {
            "영": "0", "일": "1", "이": "2", "삼": "3", "사": "4",
            "오": "5", "육": "6", "칠": "7", "팔": "8", "구": "9",
            "십": "0", "백": "00", "천": "000", "만": "0000",
        }

        for korean, digit in korean_digits.items():
            text = text.replace(korean, digit)

        return text

    @staticmethod
    def clean_table_cell(text: str) -> str:
        """Clean text extracted from table cell"""
        if not text:
            return ""

        # Remove extra whitespace
        text = KoreanTextProcessor.normalize_whitespace(text)

        # Remove common artifacts
        text = text.replace("\xa0", " ")  # Non-breaking space
        text = text.replace("\t", " ")

        # Remove leading/trailing special characters
        text = text.strip(".,;:-_=+*#@!~`")

        return text.strip()
