"""Tests for database operations"""

import pytest
from datetime import date, timedelta

from kb_lockup.core.models import LockupData, ReminderConfig


@pytest.mark.asyncio
async def test_insert_lockup(db, sample_lockup_data):
    """Test inserting lockup data"""
    row_id = await db.insert_lockup(sample_lockup_data)
    assert row_id > 0


@pytest.mark.asyncio
async def test_search_lockup_by_company(db, sample_lockup_data):
    """Test searching by company name"""
    await db.insert_lockup(sample_lockup_data)

    results = await db.search_lockup("삼성전자")
    assert len(results) == 1
    assert results[0].company_name == "삼성전자"
    assert results[0].owner == "홍길동"


@pytest.mark.asyncio
async def test_search_lockup_by_stock_code(db, sample_lockup_data):
    """Test searching by stock code"""
    await db.insert_lockup(sample_lockup_data)

    results = await db.search_lockup("005930")
    assert len(results) == 1
    assert results[0].stock_code == "005930"


@pytest.mark.asyncio
async def test_get_upcoming_unlocks(db):
    """Test getting upcoming unlocks"""
    # Insert data with future release date
    future_date = date.today() + timedelta(days=10)
    data = LockupData(
        company_name="테스트회사",
        owner="테스트주주",
        amount=100000,
        ratio=5.0,
        release_date=future_date,
    )
    await db.insert_lockup(data)

    # Should find the unlock within 30 days
    results = await db.get_upcoming_unlocks(days=30)
    assert len(results) == 1
    assert results[0].company_name == "테스트회사"

    # Should not find within 5 days
    results = await db.get_upcoming_unlocks(days=5)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_get_upcoming_unlocks_with_min_ratio(db):
    """Test filtering upcoming unlocks by minimum ratio"""
    future_date = date.today() + timedelta(days=10)

    # Insert low ratio
    data1 = LockupData(
        company_name="회사1",
        owner="주주1",
        ratio=1.0,
        release_date=future_date,
    )
    await db.insert_lockup(data1)

    # Insert high ratio
    data2 = LockupData(
        company_name="회사2",
        owner="주주2",
        ratio=10.0,
        release_date=future_date,
    )
    await db.insert_lockup(data2)

    # Filter by min_ratio=5.0
    results = await db.get_upcoming_unlocks(days=30, min_ratio=5.0)
    assert len(results) == 1
    assert results[0].company_name == "회사2"


@pytest.mark.asyncio
async def test_add_reminder(db):
    """Test adding reminder"""
    reminder = ReminderConfig(
        telegram_chat_id=12345,
        company_name="삼성전자",
        days_before=7,
        min_ratio=1.0,
    )

    reminder_id = await db.add_reminder(reminder)
    assert reminder_id > 0

    # Retrieve reminders
    reminders = await db.get_reminders(chat_id=12345)
    assert len(reminders) == 1
    assert reminders[0].company_name == "삼성전자"


@pytest.mark.asyncio
async def test_deactivate_reminder(db):
    """Test deactivating reminder"""
    reminder = ReminderConfig(
        telegram_chat_id=12345,
        company_name="테스트",
        days_before=7,
    )

    reminder_id = await db.add_reminder(reminder)

    # Deactivate
    success = await db.deactivate_reminder(reminder_id)
    assert success

    # Should not appear in active reminders
    reminders = await db.get_reminders(chat_id=12345, active_only=True)
    assert len(reminders) == 0


@pytest.mark.asyncio
async def test_duplicate_prevention(db):
    """Test that duplicate entries are handled"""
    data = LockupData(
        company_name="테스트회사",
        owner="테스트주주",
        release_date=date(2024, 6, 15),
    )

    # Insert twice
    await db.insert_lockup(data)
    await db.insert_lockup(data)

    # Should only have one entry (due to UNIQUE constraint)
    results = await db.search_lockup("테스트회사")
    assert len(results) == 1
