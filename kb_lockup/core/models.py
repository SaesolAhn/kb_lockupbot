"""Pydantic models for KB Lockup"""

from datetime import date, datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


class Market(str, Enum):
    """Korean stock market types"""
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
    sector: Optional[str] = None


class LockupEntry(BaseModel):
    """Single lockup row from extracted table"""
    owner: str = Field(..., description="Shareholder name")
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
    lockup_signal: bool = False
    strong_lockup: bool = False
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
    stock_code: Optional[str] = None
    owner: str
    amount: int
    ratio: float
    release_date: date
    days_until_unlock: int
    current_price: Optional[float] = None
    value_estimate: Optional[float] = None
    avg_daily_volume: Optional[int] = None
    days_to_exit: Optional[int] = None
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


class LockupData(BaseModel):
    """Database lockup entry with metadata"""
    id: Optional[int] = None
    company_name: str
    stock_code: Optional[str] = None
    listing_date: Optional[date] = None
    owner: str
    amount: Optional[int] = None
    ratio: Optional[float] = None
    release_date: Optional[date] = None
    lock_period_months: Optional[int] = None
    remarks: Optional[str] = None
    source_rcept_no: Optional[str] = None
    source_section: Optional[str] = None
    extraction_score: Optional[float] = None
    collected_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
