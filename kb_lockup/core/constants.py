"""Korean keywords, patterns, and constants for lockup extraction"""

# Lockup-related keywords
LOCKUP_KEYWORDS = {
    "primary": [
        "보호예수",
        "의무보유",
        "매각제한",
        "lock-up",
        "lockup",
        "락업",
    ],
    "secondary": [
        "매도제한",
        "보유확약",
        "의무보유확약",
        "매각금지",
    ]
}

# Table column keywords for identification
COLUMN_KEYWORDS = {
    "owner": ["주주명", "성명", "보유자", "주주", "예수자", "주식보유자", "소유자"],
    "amount": ["보유량", "주식수", "수량", "보유주식수", "예수수량", "주식수량", "보유수량"],
    "ratio": ["지분율", "지분", "비율", "보유비율", "소유비율", "지분비율"],
    "release_date": ["해제일", "매각가능일", "만료일", "종료일", "예수해제일", "보호예수해제일"],
    "period": ["기간", "보호예수기간", "의무보유기간", "매각제한기간", "예수기간"],
}

# Document section keywords to locate lockup tables
SECTION_KEYWORDS = [
    "최대주주등의 주식보유현황",
    "보호예수 현황",
    "의무보유 현황",
    "주식등의 매각제한",
    "주요주주의 주식소유현황",
    "주식의 보호예수",
    "의무보유확약 현황",
    "매각제한 주식",
]

# DART report type codes
DART_REPORT_TYPES = {
    "prospectus": "I",  # 증권신고서
    "ipo_registration": "I001",  # IPO 관련
}

# Date format patterns for Korean documents
DATE_PATTERNS = [
    r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일",  # 2024년 1월 15일
    r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})",    # 2024.01.15, 2024-01-15
    r"(\d{4})(\d{2})(\d{2})",                   # 20240115
]

# Relative date patterns
RELATIVE_DATE_PATTERNS = [
    (r"상장일로부터\s*(\d+)\s*개월", "months"),
    (r"상장일로부터\s*(\d+)\s*년", "years"),
    (r"상장\s*후\s*(\d+)\s*개월", "months"),
    (r"상장\s*후\s*(\d+)\s*년", "years"),
]

# Amount format patterns
AMOUNT_PATTERNS = [
    (r"([\d,]+)\s*주", 1),           # 1,234,567주
    (r"([\d.]+)\s*만\s*주", 10000),  # 123.4만주
    (r"([\d.]+)\s*천\s*주", 1000),   # 1,234천주
    (r"([\d.]+)\s*백만\s*주", 1000000),  # 1.23백만주
]

# Ratio format patterns
RATIO_PATTERNS = [
    r"([\d.]+)\s*%",      # 12.34%
    r"([\d.]+)\s*퍼센트",  # 12.34퍼센트
]

# Table relevance scoring weights
SCORING_WEIGHTS = {
    "strong_keyword": 1.0,
    "secondary_keyword": 0.5,
    "column_match": 0.3,
    "section_match": 0.4,
    "row_count_bonus": 0.1,  # Per row, max 0.5
}
