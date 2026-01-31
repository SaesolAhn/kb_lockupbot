"""Analysis page - blockdeal and exit analysis"""

import streamlit as st
import pandas as pd

from kb_lockup.storage.database import Database
from kb_lockup.analysis.blockdeal import BlockdealAnalyzer
from kb_lockup.analysis.exit_analysis import ExitAnalyzer
from kb_lockup.web.utils import run_async


def render():
    """Render analysis page"""
    st.title("📈 분석")

    tab1, tab2 = st.tabs(["블록딜 기회", "청산 분석"])

    with tab1:
        render_blockdeal_tab()

    with tab2:
        render_exit_tab()


def render_blockdeal_tab():
    """Render blockdeal opportunities tab"""
    st.header("💰 블록딜 기회")

    col1, col2, col3 = st.columns(3)

    with col1:
        days_ahead = st.number_input(
            "분석 기간 (일)",
            min_value=1,
            max_value=365,
            value=30,
            key="bd_days",
        )

    with col2:
        min_ratio = st.number_input(
            "최소 지분율 (%)",
            min_value=0.0,
            max_value=50.0,
            value=1.0,
            step=0.5,
            key="bd_ratio",
        )

    with col3:
        min_amount = st.number_input(
            "최소 주식수",
            min_value=0,
            value=0,
            step=10000,
            key="bd_amount",
        )

    if st.button("분석 실행", key="bd_analyze"):
        with st.spinner("분석 중..."):
            opportunities = run_async(
                analyze_blockdeal(days_ahead, min_ratio, min_amount or None)
            )

        if not opportunities:
            st.info("해당 조건의 기회가 없습니다.")
            return

        st.success(f"{len(opportunities)}건의 기회를 발견했습니다.")

        df = pd.DataFrame([
            {
                "회사명": o.company_name,
                "종목코드": o.stock_code or "-",
                "주주명": o.owner,
                "보유량": o.amount,
                "지분율(%)": o.ratio,
                "해제일": o.release_date.isoformat(),
                "D-Day": o.days_until_unlock,
                "기회점수": o.opportunity_score,
            }
            for o in opportunities
        ])

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "보유량": st.column_config.NumberColumn(format="%d"),
                "지분율(%)": st.column_config.NumberColumn(format="%.2f"),
                "기회점수": st.column_config.ProgressColumn(
                    min_value=0,
                    max_value=100,
                    format="%.1f",
                ),
            },
        )


def render_exit_tab():
    """Render exit analysis tab"""
    st.header("🚪 청산 분석")

    st.info(
        "청산 분석은 대량 보유 주주가 보유 주식을 매각할 때 "
        "예상되는 시장 영향을 분석합니다."
    )

    col1, col2 = st.columns(2)

    with col1:
        days_ahead = st.number_input(
            "분석 기간 (일)",
            min_value=1,
            max_value=365,
            value=60,
            key="exit_days",
        )

    with col2:
        min_ratio = st.number_input(
            "최소 지분율 (%)",
            min_value=0.0,
            max_value=50.0,
            value=1.0,
            step=0.5,
            key="exit_ratio",
        )

    if st.button("분석 실행", key="exit_analyze"):
        with st.spinner("분석 중..."):
            results = run_async(analyze_exit(days_ahead, min_ratio))

        if not results:
            st.info("해당 조건의 데이터가 없습니다.")
            return

        st.success(f"{len(results)}건의 결과")

        # Check if we have market data
        has_market_data = any(o.current_price for o in results)

        if has_market_data:
            df = pd.DataFrame([
                {
                    "회사명": o.company_name,
                    "종목코드": o.stock_code or "-",
                    "주주명": o.owner,
                    "보유량": o.amount,
                    "지분율(%)": o.ratio,
                    "해제일": o.release_date.isoformat(),
                    "D-Day": o.days_until_unlock,
                    "현재가": o.current_price,
                    "추정가치(억)": round(o.value_estimate / 100_000_000, 1) if o.value_estimate else None,
                    "일평균거래량": o.avg_daily_volume,
                    "예상청산일수": o.days_to_exit,
                }
                for o in results
            ])

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "보유량": st.column_config.NumberColumn(format="%d"),
                    "현재가": st.column_config.NumberColumn(format="%d원"),
                    "일평균거래량": st.column_config.NumberColumn(format="%d"),
                    "예상청산일수": st.column_config.NumberColumn(format="%d일"),
                },
            )
        else:
            df = pd.DataFrame([
                {
                    "회사명": o.company_name,
                    "종목코드": o.stock_code or "-",
                    "주주명": o.owner,
                    "보유량": o.amount,
                    "지분율(%)": o.ratio,
                    "해제일": o.release_date.isoformat(),
                    "D-Day": o.days_until_unlock,
                    "예상청산일수": o.days_to_exit or "N/A",
                }
                for o in results
            ])

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )

        # Note about market data
        from kb_lockup.analysis.market_data import get_market_data_service
        market_svc = get_market_data_service()
        if market_svc.is_available():
            st.caption("✅ 시장 데이터 연동 활성화 - pykrx 사용 중 (KRX 거래량/가격 데이터)")
        else:
            st.caption(
                "⚠️ 예상청산일수는 실제 거래량 데이터가 필요합니다. "
                "`pip install pykrx` 설치 후 이용 가능합니다."
            )


async def analyze_blockdeal(
    days_ahead: int,
    min_ratio: float,
    min_amount: int = None,
) -> list:
    """Run blockdeal analysis"""
    try:
        async with Database() as db:
            analyzer = BlockdealAnalyzer(db)
            return await analyzer.find_opportunities(
                days_ahead=days_ahead,
                min_ratio=min_ratio,
                min_amount=min_amount,
            )
    except Exception as e:
        st.error(f"분석 실패: {e}")
        return []


async def analyze_exit(days_ahead: int, min_ratio: float) -> list:
    """Run exit analysis"""
    try:
        async with Database() as db:
            analyzer = ExitAnalyzer(db)
            return await analyzer.analyze_exit_candidates(
                days_ahead=days_ahead,
                min_ratio=min_ratio,
            )
    except Exception as e:
        st.error(f"분석 실패: {e}")
        return []
