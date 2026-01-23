"""Dashboard page - overview and statistics"""

import asyncio
from datetime import date

import streamlit as st
import pandas as pd

from kb_lockup.storage.database import Database


def render():
    """Render dashboard page"""
    st.title("📊 대시보드")

    # Load data
    data = asyncio.run(load_dashboard_data())

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "전체 보호예수 건수",
            data["total_lockups"],
        )

    with col2:
        st.metric(
            "7일 내 해제",
            data["unlocks_7d"],
            delta=f"{data['unlocks_7d']}건",
        )

    with col3:
        st.metric(
            "30일 내 해제",
            data["unlocks_30d"],
        )

    with col4:
        st.metric(
            "등록 회사 수",
            data["total_companies"],
        )

    st.markdown("---")

    # Upcoming unlocks
    st.header("📅 다가오는 보호예수 해제")

    if data["upcoming"]:
        df = pd.DataFrame([
            {
                "회사명": lockup.company_name,
                "종목코드": lockup.stock_code or "-",
                "주주명": lockup.owner,
                "보유량": f"{lockup.amount:,}" if lockup.amount else "-",
                "지분율": f"{lockup.ratio:.1f}%" if lockup.ratio else "-",
                "해제일": lockup.release_date.isoformat() if lockup.release_date else "-",
                "D-Day": (lockup.release_date - date.today()).days if lockup.release_date else "-",
            }
            for lockup in data["upcoming"][:20]
        ])

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("다가오는 보호예수 해제 일정이 없습니다.")

    st.markdown("---")

    # Large positions
    st.header("💰 대형 보호예수 (지분율 5% 이상)")

    if data["large_positions"]:
        df_large = pd.DataFrame([
            {
                "회사명": lockup.company_name,
                "주주명": lockup.owner,
                "지분율": f"{lockup.ratio:.1f}%" if lockup.ratio else "-",
                "보유량": f"{lockup.amount:,}" if lockup.amount else "-",
                "해제일": lockup.release_date.isoformat() if lockup.release_date else "-",
            }
            for lockup in data["large_positions"][:10]
        ])

        st.dataframe(
            df_large,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("대형 보호예수 데이터가 없습니다.")


async def load_dashboard_data() -> dict:
    """Load data for dashboard"""
    try:
        async with Database() as db:
            # Get upcoming unlocks
            upcoming_7d = await db.get_upcoming_unlocks(days=7)
            upcoming_30d = await db.get_upcoming_unlocks(days=30)
            large = await db.get_upcoming_unlocks(days=365, min_ratio=5.0)

            # Count total lockups
            cursor = await db.conn.execute("SELECT COUNT(*) FROM lockup_data")
            total = (await cursor.fetchone())[0]

            # Count companies
            cursor = await db.conn.execute(
                "SELECT COUNT(DISTINCT company_name) FROM lockup_data"
            )
            companies = (await cursor.fetchone())[0]

            return {
                "total_lockups": total,
                "unlocks_7d": len(upcoming_7d),
                "unlocks_30d": len(upcoming_30d),
                "total_companies": companies,
                "upcoming": upcoming_30d,
                "large_positions": large,
            }
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return {
            "total_lockups": 0,
            "unlocks_7d": 0,
            "unlocks_30d": 0,
            "total_companies": 0,
            "upcoming": [],
            "large_positions": [],
        }
