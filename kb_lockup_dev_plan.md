# KB Lockup - Development Plan & Schema

## Project Overview

KB Lockup is a system for extracting and analyzing shareholder lockup schedules from Korean DART filings, helping investors track when locked-up shares become tradeable after IPOs.

---

## 1. Project Structure

```
kb_lockup/
├── __init__.py
├── main.py                      # Entry point, CLI commands
├── config.py                    # Settings, API keys, paths
│
├── core/
│   ├── __init__.py
│   ├── models.py                # Pydantic/dataclass models
│   ├── constants.py             # Korean keywords, patterns, enums
│   └── exceptions.py            # Custom exceptions
│
├── dart/
│   ├── __init__.py
│   ├── api.py                   # DART OpenAPI client
│   ├── parser.py                # Document/XML parsing
│   └── downloader.py            # Prospectus document fetcher
│
├── extraction/
│   ├── __init__.py
│   ├── table_finder.py          # Identify lockup tables in documents
│   ├── qwen_extractor.py        # Qwen API for variable table layouts
│   ├── normalizer.py            # Standardize dates, amounts, ratios
│   └── scorer.py                # Rank/score table candidates
│
├── storage/
│   ├── __init__.py
│   ├── database.py              # SQLite operations
│   ├── cache.py                 # Response/metadata caching
│   └── migrations.py            # Schema versioning
│
├── analysis/
│   ├── __init__.py
│   ├── blockdeal.py             # Blockdeal opportunity detection
│   ├── exit_analysis.py         # Exit trading candidates
│   └── alerts.py                # Threshold-based alerting logic
│
├── export/
│   ├── __init__.py
│   ├── excel.py                 # xlwings add-in, xlsx generation
│   └── formatter.py             # Message formatting for Telegram/Excel
│
├── telegram_bot/
│   ├── __init__.py
│   ├── bot.py                   # python-telegram-bot handlers
│   ├── commands.py              # /search, /remind, /upcoming
│   └── scheduler.py             # Reminder scheduling (APScheduler)
│
├── web/
│   ├── __init__.py
│   ├── app.py                   # Streamlit main app
│   ├── pages/
│   │   ├── search.py            # Search lockup data
│   │   ├── dashboard.py         # Overview/statistics
│   │   └── analysis.py          # Blockdeal/exit views
│   └── components.py            # Reusable Streamlit widgets
│
└── utils/
    ├── __init__.py
    ├── korean.py                # Korean text processing
    ├── date_utils.py            # Date parsing (Korean formats)
    └── validators.py            # Input validation
```

---

## 2. Database Schema

### 2.1 SQLite Tables

```sql
-- Core lockup data table
CREATE TABLE IF NOT EXISTS lockup_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    stock_code TEXT,                          -- 6-digit KRX code
    listing_date TEXT,                        -- YYYY-MM-DD format
    owner TEXT NOT NULL,                      -- 주주명, 성명
    amount INTEGER,                           -- Number of shares
    ratio REAL,                               -- Ownership % (0-100)
    release_date TEXT,                        -- Lockup release date
    lock_period_months INTEGER,               -- Lock period in months
    remarks TEXT,                             -- Additional notes
    source_rcept_no TEXT,                     -- DART receipt number
    source_section TEXT,                      -- Section title where found
    extraction_score REAL,                    -- Confidence score (0-1)
    collected_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT,
    
    UNIQUE(company_name, owner, release_date) -- Prevent duplicates
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_lockup_company ON lockup_data(company_name);
CREATE INDEX IF NOT EXISTS idx_lockup_stock_code ON lockup_data(stock_code);
CREATE INDEX IF NOT EXISTS idx_lockup_release_date ON lockup_data(release_date);
CREATE INDEX IF NOT EXISTS idx_lockup_owner ON lockup_data(owner);

-- Company metadata cache
CREATE TABLE IF NOT EXISTS companies (
    corp_code TEXT PRIMARY KEY,               -- DART corp code
    corp_name TEXT NOT NULL,
    stock_code TEXT,                          -- KRX 6-digit code
    listing_date TEXT,
    market TEXT,                              -- KOSPI, KOSDAQ, KONEX
    sector TEXT,
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_company_name ON companies(corp_name);
CREATE INDEX IF NOT EXISTS idx_company_stock ON companies(stock_code);

-- Prospectus document tracking
CREATE TABLE IF NOT EXISTS prospectuses (
    rcept_no TEXT PRIMARY KEY,                -- DART receipt number
    corp_code TEXT NOT NULL,
    report_nm TEXT,                           -- Report name
    rcept_dt TEXT,                            -- Filing date
    processed INTEGER DEFAULT 0,              -- 0=pending, 1=done, -1=failed
    extraction_method TEXT,                   -- 'qwen', 'regex', 'manual'
    tables_found INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    processed_at TEXT,
    error_message TEXT,
    
    FOREIGN KEY (corp_code) REFERENCES companies(corp_code)
);

-- Reminder/alert subscriptions
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id INTEGER NOT NULL,
    company_name TEXT,
    stock_code TEXT,
    owner TEXT,                               -- Specific shareholder (optional)
    min_ratio REAL DEFAULT 1.0,               -- Minimum stake % to alert
    min_amount INTEGER,                       -- Minimum share count
    days_before INTEGER DEFAULT 7,            -- Days before release to notify
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_reminder_chat ON reminders(telegram_chat_id);

-- Exit opportunity analysis results (materialized view pattern)
CREATE TABLE IF NOT EXISTS exit_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    stock_code TEXT,
    owner TEXT NOT NULL,
    amount INTEGER,
    ratio REAL,
    release_date TEXT NOT NULL,
    days_until_unlock INTEGER,
    current_price REAL,                       -- Last known price
    value_estimate REAL,                      -- amount * current_price
    avg_daily_volume INTEGER,                 -- For liquidity analysis
    days_to_exit INTEGER,                     -- Estimated exit duration
    opportunity_score REAL,                   -- Composite score
    calculated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- API response cache
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    expires_at TEXT
);
```

### 2.2 Pydantic Models (core/models.py)

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from enum import Enum
import pandas as pd

class Market(str, Enum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    KONEX = "KONEX"

class Company(BaseModel):
    """DART company lookup result"""
    corp_code: str = Field(..., description="DART corporation code")
    corp_name: str = Field(..., description="Company name")
    stock_code: Optional[str] = Field(None, description="6-digit KRX stock code")
    listing_date: Optional[date] = None
    market: Optional[Market] = None

class LockupEntry(BaseModel):
    """Single lockup row from extracted table"""
    owner: str = Field(..., description="Shareholder name (주주명)")
    amount: Optional[int] = Field(None, description="Number of shares")
    ratio: Optional[float] = Field(None, ge=0, le=100, description="Ownership %")
    release_date: Optional[date] = Field(None, description="Lockup release date")
    period_months: Optional[int] = Field(None, description="Lock period in months")
    remarks: Optional[str] = None
    
    class Config:
        json_encoders = {date: lambda v: v.isoformat() if v else None}

class TableCandidate(BaseModel):
    """Candidate table before final selection"""
    section_title: str
    context_text: Optional[str] = None
    raw_html: Optional[str] = None
    score: float = Field(0.0, ge=0, le=1, description="Relevance score")
    lockup_signal: bool = False          # Contains lockup keywords
    strong_lockup: bool = False          # High confidence lockup table
    column_headers: List[str] = []
    row_count: int = 0
    
class LockupResult(BaseModel):
    """Complete extraction result for a company"""
    company: Company
    rcept_no: str = Field(..., description="DART receipt number")
    section_title: Optional[str] = None
    entries: List[LockupEntry] = []
    extraction_method: str = "qwen"
    confidence_score: float = Field(0.0, ge=0, le=1)
    extracted_at: datetime = Field(default_factory=datetime.now)
    
class ProspectusInfo(BaseModel):
    """Prospectus document metadata"""
    rcept_no: str
    corp_code: str
    report_nm: str
    rcept_dt: date
    
class ExitOpportunity(BaseModel):
    """Blockdeal/exit analysis result"""
    company_name: str
    stock_code: Optional[str]
    owner: str
    amount: int
    ratio: float
    release_date: date
    days_until_unlock: int
    current_price: Optional[float] = None
    value_estimate: Optional[float] = None
    avg_daily_volume: Optional[int] = None
    days_to_exit: Optional[int] = None      # amount / avg_daily_volume
    opportunity_score: Optional[float] = None

class ReminderConfig(BaseModel):
    """Telegram reminder subscription"""
    telegram_chat_id: int
    company_name: Optional[str] = None
    stock_code: Optional[str] = None
    owner: Optional[str] = None
    min_ratio: float = 1.0
    min_amount: Optional[int] = None
    days_before: int = 7
    active: bool = True
```

---

## 3. Core Component Specifications

### 3.1 DART API Client (dart/api.py)

```python
class DartAPI:
    """
    DART OpenAPI client for:
    - Company list retrieval (기업개황)
    - Document search (공시검색)  
    - Document content fetch (공시서류원본파일)
    """
    
    BASE_URL = "https://opendart.fss.or.kr/api"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = httpx.AsyncClient(timeout=30.0)
    
    async def get_corp_code(self, company_name: str) -> Optional[str]:
        """Find corp_code by company name (fuzzy match)"""
        
    async def search_prospectuses(
        self, 
        corp_code: str,
        bgn_de: str,  # Start date YYYYMMDD
        end_de: str,  # End date YYYYMMDD
    ) -> List[ProspectusInfo]:
        """Search for 증권신고서 filings"""
        # pblntf_ty = "I" for 증권신고서
        
    async def get_document(self, rcept_no: str) -> bytes:
        """Download document ZIP file"""
        
    async def get_document_xml(self, rcept_no: str) -> str:
        """Get document as parsed XML/HTML"""
```

### 3.2 Table Extraction (extraction/qwen_extractor.py)

```python
class QwenTableExtractor:
    """
    Use Qwen API (via OpenAI-compatible endpoint) for 
    variable table layout extraction
    """
    
    SYSTEM_PROMPT = """
    You are an expert at extracting shareholder lockup schedules from Korean 
    financial documents. Extract tables containing:
    - 주주명/성명 (Shareholder name)
    - 보유량/주식수 (Share amount)
    - 지분율 (Ownership ratio %)
    - 보호예수/의무보유 기간 (Lock period)
    - 해제일/매각가능일 (Release date)
    
    Return structured JSON with all lockup entries found.
    """
    
    def __init__(self, api_key: str, model: str = "qwen-plus"):
        from openai import OpenAI
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.model = model
    
    async def extract_tables(
        self, 
        document_text: str,
        table_candidates: List[TableCandidate]
    ) -> List[LockupEntry]:
        """
        Send table candidates to Qwen for structured extraction
        Returns normalized LockupEntry list
        """
        
    def _build_prompt(self, table_html: str, context: str) -> str:
        """Build extraction prompt with table context"""
```

### 3.3 Table Scoring (extraction/scorer.py)

```python
class TableScorer:
    """Score and rank table candidates for lockup relevance"""
    
    # Korean lockup keywords with weights
    STRONG_SIGNALS = {
        "보호예수": 1.0,
        "의무보유": 1.0,
        "매각제한": 0.9,
        "lock-up": 0.9,
        "lockup": 0.9,
    }
    
    COLUMN_SIGNALS = {
        "주주명": 0.3,
        "성명": 0.2,
        "보유량": 0.3,
        "지분율": 0.3,
        "해제일": 0.4,
        "기간": 0.2,
    }
    
    def score_table(self, candidate: TableCandidate) -> float:
        """Calculate relevance score 0-1"""
        
    def is_strong_lockup(self, candidate: TableCandidate) -> bool:
        """Check if table is definitely a lockup schedule"""
```

### 3.4 Date/Amount Normalizer (extraction/normalizer.py)

```python
class KoreanNormalizer:
    """Normalize Korean date formats and number expressions"""
    
    DATE_PATTERNS = [
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일",  # 2024년 1월 15일
        r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})",    # 2024.01.15
        r"상장일로부터\s*(\d+)\s*(개월|년)",         # 상장일로부터 6개월
    ]
    
    def normalize_date(
        self, 
        raw_date: str, 
        listing_date: Optional[date] = None
    ) -> Optional[date]:
        """Parse various Korean date formats"""
        
    def normalize_amount(self, raw_amount: str) -> Optional[int]:
        """Parse share amounts: '1,234,567주', '123만주' etc."""
        
    def normalize_ratio(self, raw_ratio: str) -> Optional[float]:
        """Parse ratios: '12.34%', '12.34' etc."""
```

---

## 4. Telegram Bot Specification

### 4.1 Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/search <query>` | Search by company name or code | `/search 삼성전자` or `/search 005930` |
| `/upcoming [days]` | List unlocks in next N days | `/upcoming 30` |
| `/remind <company> <days>` | Set reminder for unlock | `/remind 카카오 7` |
| `/reminders` | List active reminders | `/reminders` |
| `/cancel <id>` | Cancel a reminder | `/cancel 3` |
| `/blockdeal [min_ratio]` | Large position opportunities | `/blockdeal 5` |
| `/export <company>` | Get Excel file | `/export 네이버` |
| `/help` | Show command list | `/help` |

### 4.2 Bot Architecture (telegram_bot/bot.py)

```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class KBLockupBot:
    def __init__(self, token: str, db: Database):
        self.app = Application.builder().token(token).build()
        self.db = db
        self.scheduler = AsyncIOScheduler()
        self._setup_handlers()
        self._setup_scheduler()
    
    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("search", self.search_handler))
        self.app.add_handler(CommandHandler("upcoming", self.upcoming_handler))
        self.app.add_handler(CommandHandler("remind", self.remind_handler))
        self.app.add_handler(CommandHandler("blockdeal", self.blockdeal_handler))
        self.app.add_handler(CommandHandler("export", self.export_handler))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
    
    def _setup_scheduler(self):
        """Schedule daily reminder checks"""
        self.scheduler.add_job(
            self.check_reminders,
            'cron',
            hour=8,
            minute=0,
            timezone='Asia/Seoul'
        )
    
    async def search_handler(self, update: Update, context):
        """Handle /search command"""
        
    async def format_lockup_message(self, entries: List[LockupEntry]) -> str:
        """Format lockup data for Telegram"""
```

### 4.3 Message Formats

```
📊 **삼성전자 (005930) 보호예수 현황**

┌─────────────────────────────────
│ 주주명: 이재용
│ 보유량: 1,234,567주 (12.34%)
│ 해제일: 2024-06-15 (D-45)
└─────────────────────────────────

┌─────────────────────────────────
│ 주주명: 국민연금
│ 보유량: 987,654주 (9.87%)
│ 해제일: 2024-07-01 (D-61)
└─────────────────────────────────

총 2건 | 업데이트: 2024-05-01
```

---

## 5. Streamlit Web App Specification

### 5.1 Pages

1. **Dashboard** (`pages/dashboard.py`)
   - Summary statistics (total companies, upcoming unlocks)
   - Calendar heatmap of unlock dates
   - Top 10 largest upcoming unlocks

2. **Search** (`pages/search.py`)
   - Company name / stock code search
   - Date range filter
   - Minimum stake % filter
   - Results table with export button

3. **Analysis** (`pages/analysis.py`)
   - Blockdeal opportunities tab
   - Exit trading candidates tab
   - Volume analysis charts

4. **Admin** (`pages/admin.py`)
   - Manual extraction trigger
   - Processing queue status
   - Error logs

### 5.2 App Structure (web/app.py)

```python
import streamlit as st

st.set_page_config(
    page_title="KB Lockup",
    page_icon="🔒",
    layout="wide"
)

# Sidebar navigation
page = st.sidebar.selectbox(
    "페이지 선택",
    ["대시보드", "검색", "분석", "관리"]
)

# Page routing
if page == "대시보드":
    from pages.dashboard import render
elif page == "검색":
    from pages.search import render
# ...

render()
```

---

## 6. Excel Integration

### 6.1 xlwings Add-in Functions

```python
import xlwings as xw

@xw.func
def kb_lockup_search(company_name: str) -> list:
    """Excel function: =kb_lockup_search("삼성전자")"""
    db = Database()
    results = db.search_lockup(company_name)
    return [[r.owner, r.amount, r.ratio, r.release_date] for r in results]

@xw.func  
def kb_upcoming_unlocks(days: int = 30) -> list:
    """Excel function: =kb_upcoming_unlocks(30)"""
    db = Database()
    results = db.get_upcoming_unlocks(days)
    return [[r.company_name, r.owner, r.amount, r.release_date] for r in results]
```

### 6.2 Search_Tool.xlsx Template

| Column | Purpose |
|--------|---------|
| A | Search input (company name/code) |
| B | Search button (linked to macro) |
| C-H | Results table (auto-populated) |
| I | Export to separate sheet button |

---

## 7. Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)

**Tasks:**
1. [ ] Set up project structure and dependencies
2. [ ] Implement SQLite database layer with migrations
3. [ ] Build DART API client with rate limiting
4. [ ] Create Pydantic models and validators
5. [ ] Implement basic caching layer

**Deliverables:**
- Working database with all tables
- DART API integration (company lookup, document search)
- Unit tests for core models

### Phase 2: Extraction Engine (Week 3-4)

**Tasks:**
1. [ ] Build document parser (XML/HTML handling)
2. [ ] Implement table finder with Korean keyword detection
3. [ ] Integrate Qwen API for table extraction
4. [ ] Build table scorer and ranker
5. [ ] Create normalizer for dates/amounts/ratios
6. [ ] Implement extraction pipeline orchestrator

**Deliverables:**
- End-to-end extraction from DART filing to database
- Confidence scoring for extractions
- Error handling and retry logic

### Phase 3: Telegram Bot (Week 5)

**Tasks:**
1. [ ] Set up python-telegram-bot framework
2. [ ] Implement all command handlers
3. [ ] Build reminder scheduler with APScheduler
4. [ ] Create message formatters
5. [ ] Add inline keyboard navigation

**Deliverables:**
- Fully functional Telegram bot
- Working reminder system
- Excel export from bot

### Phase 4: Web Interface (Week 6)

**Tasks:**
1. [ ] Build Streamlit app structure
2. [ ] Implement search page with filters
3. [ ] Create dashboard with visualizations
4. [ ] Build analysis pages (blockdeal, exit)
5. [ ] Add admin/management page

**Deliverables:**
- Deployed Streamlit app
- Interactive search and analysis
- Data visualization

### Phase 5: Excel Integration & Polish (Week 7)

**Tasks:**
1. [ ] Create xlwings add-in
2. [ ] Build Search_Tool.xlsx template
3. [ ] Write user documentation
4. [ ] Performance optimization
5. [ ] Error handling improvements

**Deliverables:**
- Working Excel add-in
- Complete documentation
- Production-ready system

---

## 8. Configuration (config.py)

```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # API Keys
    dart_api_key: str
    qwen_api_key: str
    telegram_bot_token: str
    
    # Database
    db_path: Path = Path("data/kb_lockup.db")
    
    # DART settings
    dart_rate_limit: int = 1000  # requests per day
    
    # Extraction settings
    qwen_model: str = "qwen-plus"
    min_extraction_score: float = 0.6
    
    # Telegram settings
    reminder_check_hour: int = 8
    
    # Paths
    data_dir: Path = Path("data")
    export_dir: Path = Path("exports")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

---

## 9. Dependencies (requirements.txt)

```
# Core
pydantic>=2.0
pydantic-settings>=2.0
python-dotenv>=1.0

# DART API
httpx>=0.25
aiohttp>=3.9

# AI Extraction
openai>=1.0  # For Qwen API compatibility

# Database
aiosqlite>=0.19

# Telegram
python-telegram-bot>=20.0
apscheduler>=3.10

# Web
streamlit>=1.30

# Excel
xlwings>=0.30
openpyxl>=3.1
pandas>=2.0

# Parsing
beautifulsoup4>=4.12
lxml>=5.0

# Utilities
tenacity>=8.0  # Retry logic
loguru>=0.7    # Logging

# Dev
pytest>=7.0
pytest-asyncio>=0.21
black>=23.0
ruff>=0.1
```

---

## 10. Key Korean Constants (core/constants.py)

```python
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
    ]
}

# Table column keywords
COLUMN_KEYWORDS = {
    "owner": ["주주명", "성명", "보유자", "주주", "예수자"],
    "amount": ["보유량", "주식수", "수량", "보유주식수", "예수수량"],
    "ratio": ["지분율", "지분", "비율", "보유비율"],
    "release_date": ["해제일", "매각가능일", "만료일", "종료일"],
    "period": ["기간", "보호예수기간", "의무보유기간"],
}

# Document section keywords
SECTION_KEYWORDS = [
    "최대주주등의 주식보유현황",
    "보호예수 현황",
    "의무보유 현황",
    "주식등의 매각제한",
    "주요주주의 주식소유현황",
]
```

---

## 11. Error Handling Strategy

```python
# core/exceptions.py

class KBLockupError(Exception):
    """Base exception"""
    pass

class DartAPIError(KBLockupError):
    """DART API related errors"""
    pass

class ExtractionError(KBLockupError):
    """Table extraction failures"""
    pass

class ValidationError(KBLockupError):
    """Data validation failures"""
    pass

class RateLimitError(DartAPIError):
    """API rate limit exceeded"""
    pass
```

---

## 12. Testing Strategy

```
tests/
├── conftest.py              # Fixtures
├── test_dart_api.py         # DART API tests
├── test_extraction.py       # Table extraction tests
├── test_normalizer.py       # Date/amount parsing tests
├── test_database.py         # Database operations
├── test_telegram.py         # Bot command tests
└── fixtures/
    ├── sample_prospectus.html
    └── expected_extractions.json
```

**Key test cases:**
1. Korean date format parsing (all variations)
2. Share amount normalization (만주, 천주, etc.)
3. Table scoring accuracy
4. Duplicate prevention
5. Reminder scheduling

---

## Notes for AI Coder

1. **Always handle Korean encoding**: Use UTF-8 everywhere, be careful with BeautifulSoup parsing.

2. **DART API quirks**: 
   - Rate limited (1000/day)
   - Returns XML with inconsistent formatting
   - Some documents are ZIP files containing multiple files

3. **Table extraction challenges**:
   - Tables may span multiple pages
   - Column headers vary between documents
   - Some lockup info is in prose, not tables

4. **Date calculation**:
   - Many release dates are relative ("상장일로부터 6개월")
   - Need listing_date to calculate actual dates

5. **Testing with real data**: Keep sample DART documents in fixtures for testing.
