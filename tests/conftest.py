"""Pytest fixtures and configuration"""

import asyncio
import tempfile
from pathlib import Path
from datetime import date

import pytest
import pytest_asyncio

from kb_lockup.storage.database import Database
from kb_lockup.core.models import LockupData, LockupEntry, Company


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db():
    """Create a temporary test database"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    database = Database(db_path)
    await database.connect()
    await database.init_schema()

    yield database

    await database.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def sample_company():
    """Sample company data"""
    return Company(
        corp_code="00126380",
        corp_name="삼성전자",
        stock_code="005930",
        listing_date=date(1975, 6, 11),
    )


@pytest.fixture
def sample_lockup_entry():
    """Sample lockup entry"""
    return LockupEntry(
        owner="홍길동",
        amount=1000000,
        ratio=5.5,
        release_date=date(2024, 6, 15),
        period_months=6,
        remarks="최대주주",
    )


@pytest.fixture
def sample_lockup_data():
    """Sample lockup data for database"""
    return LockupData(
        company_name="삼성전자",
        stock_code="005930",
        listing_date=date(1975, 6, 11),
        owner="홍길동",
        amount=1000000,
        ratio=5.5,
        release_date=date(2024, 6, 15),
        lock_period_months=6,
        remarks="최대주주",
        source_rcept_no="20240101000001",
        extraction_score=0.95,
    )


@pytest.fixture
def sample_html_table():
    """Sample HTML table for extraction testing"""
    return """
    <table>
        <tr>
            <th>주주명</th>
            <th>보유주식수</th>
            <th>지분율</th>
            <th>보호예수기간</th>
            <th>해제일</th>
        </tr>
        <tr>
            <td>홍길동</td>
            <td>1,000,000주</td>
            <td>5.5%</td>
            <td>6개월</td>
            <td>2024년 6월 15일</td>
        </tr>
        <tr>
            <td>김철수</td>
            <td>500,000주</td>
            <td>2.75%</td>
            <td>1년</td>
            <td>2024년 12월 15일</td>
        </tr>
    </table>
    """


@pytest.fixture
def sample_prospectus_content(sample_html_table):
    """Sample prospectus document content"""
    return f"""
    <html>
    <body>
        <h1>증권신고서</h1>
        <h2>제1부 모집 또는 매출에 관한 사항</h2>
        <p>회사명: 테스트회사</p>

        <h3>주식등의 매각제한</h3>
        <p>다음은 보호예수 현황입니다.</p>
        {sample_html_table}

        <h3>기타사항</h3>
        <p>추가 내용...</p>
    </body>
    </html>
    """
