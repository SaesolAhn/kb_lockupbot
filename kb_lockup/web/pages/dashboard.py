"""Dashboard page - overview and statistics"""

from datetime import date

import streamlit as st
import pandas as pd

from kb_lockup.storage.database import Database
from kb_lockup.analysis.market_data import get_market_data_service
from kb_lockup.web.utils import run_async


def render():
    """Render dashboard page"""
    st.title("📊 대시보드")

    # Load data
    data = run_async(load_dashboard_data())

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

    # All lockups with current value
    st.header("📋 전체 보호예수 현황")

    if data["all_lockups"]:
        market_svc = get_market_data_service()

        # Build dataframe with current value calculation
        rows = []
        for lockup in data["all_lockups"]:
            # Calculate current value if we have stock_code and amount
            current_value_eok = None
            current_price = None
            ratio = lockup.ratio

            if lockup.stock_code and lockup.amount:
                price = market_svc.get_current_price(lockup.stock_code)
                if price:
                    current_price = price
                    current_value_eok = (price * lockup.amount) / 100_000_000  # Billion KRW (억원)

                # Calculate 지분율 dynamically if not available
                if not ratio and market_svc.is_available():
                    calculated_ratio = market_svc.calculate_ownership_ratio(
                        lockup.stock_code, lockup.amount
                    )
                    if calculated_ratio:
                        ratio = calculated_ratio

            d_day = None
            d_day_display = "-"
            if lockup.release_date:
                d_day = (lockup.release_date - date.today()).days
                # Color-coded D-Day display
                if d_day <= 0:
                    d_day_display = f"🔴 D{d_day:+d}"
                elif d_day <= 7:
                    d_day_display = f"🟠 D-{d_day}"
                elif d_day <= 30:
                    d_day_display = f"🟡 D-{d_day}"
                else:
                    d_day_display = f"🟢 D-{d_day}"

            rows.append({
                "회사명": lockup.company_name,
                "종목코드": lockup.stock_code or "-",
                "주주명": lockup.owner,
                "보유량": lockup.amount,
                "지분율(%)": ratio,
                "해제일": lockup.release_date.isoformat() if lockup.release_date else "-",
                "D-Day": d_day_display,
                "현재가(원)": current_price,
                "평가금액(억원)": round(current_value_eok, 1) if current_value_eok else None,
            })

        df_all = pd.DataFrame(rows)

        # Sort by D-Day (upcoming releases first)
        df_all_sorted = df_all.copy()

        st.dataframe(
            df_all_sorted,
            use_container_width=True,
            hide_index=True,
            column_config={
                "보유량": st.column_config.NumberColumn(format="%,d"),
                "지분율(%)": st.column_config.NumberColumn(format="%.2f"),
                "현재가(원)": st.column_config.NumberColumn(format="%,d"),
                "평가금액(억원)": st.column_config.NumberColumn(format="%,.1f"),
            },
        )

        # Show market data status
        if market_svc.is_available():
            st.caption("✅ 시장 데이터 연동 - pykrx (현재가 기준 평가금액, 동적 지분율 계산)")
        else:
            st.caption("⚠️ 평가금액/지분율 계산에 pykrx 필요: pip install pykrx")
    else:
        st.info("보호예수 데이터가 없습니다.")

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

            # Get all lockups for full view
            all_lockups = await db.get_all_lockups(limit=500)

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
                "all_lockups": all_lockups,
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
            "all_lockups": [],
        }
