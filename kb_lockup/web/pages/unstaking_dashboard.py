import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta

from kb_lockup.seibro.db_utils import get_db_session
from kb_lockup.seibro.models import SeibroUnstakingSchedule
from kb_lockup.analysis.block_deal_ai import BlockDealAnalyzer
from sqlalchemy import select, and_, desc

def render():
    st.title("🔓 의무보유 해제 현황 (Unstaking Dashboard)")
    
    # --- Sidebar Filters ---
    st.sidebar.header("필터 설정")
    
    # Date Range
    today = date.today()
    start_default = today
    end_default = today + timedelta(days=30)
    
    date_cols = st.sidebar.columns(2)
    start_date = date_cols[0].date_input("시작일", start_default)
    end_date = date_cols[1].date_input("종료일", end_default)
    
    # Market Filter
    market_options = ["전체", "유가증권시장", "코스닥시장"]
    market = st.sidebar.selectbox("시장 구분", market_options)
    
    # --- Data Fetching ---
    rows = []
    with get_db_session() as session:
        query = select(SeibroUnstakingSchedule).where(
            and_(
                SeibroUnstakingSchedule.return_date >= start_date,
                SeibroUnstakingSchedule.return_date <= end_date
            )
        )
        
        if market != "전체":
            query = query.where(SeibroUnstakingSchedule.market_type == market)
            
        query = query.order_by(SeibroUnstakingSchedule.return_date.asc())
        
        results = session.execute(query).scalars().all()
        # Convert to list of dicts for DataFrame
        for r in results:
            rows.append({
                "id": r.id,
                "code": r.short_code,
                "company": r.company_name,
                "market": r.market_type,
                "return_date": r.return_date,
                "shares": r.return_shares,
                "stake_pct": float(r.stake_portion_pct) if r.stake_portion_pct else 0.0,
                "value_krw": float(r.current_stake_value_million_krw) if r.current_stake_value_million_krw else 0.0,
                "reason": r.reason,
                "bd_score": r.block_deal_score,
                "bd_analysis": r.block_deal_analysis
            })
            
    # --- Main Content ---
    
    if not rows:
        st.info("조건에 맞는 데이터가 없습니다.")
        return

    df = pd.DataFrame(rows)
    
    # Formatting
    st.metric("기간 내 해제 종목 수", f"{len(df)}개")
    
    # Display Table with Highlighting
    # We want to format numbers
    
    # AI Analysis Button (Batch)
    if st.button("🤖 AI 블록딜 위험 분석 실행 (표시된 항목)"):
        analyzer = BlockDealAnalyzer()
        progress_bar = st.progress(0)
        
        updated_count = 0
        with get_db_session() as session:
            for idx, row_data in enumerate(rows):
                # Skip if already analyzed (optional, but maybe force refresh?)
                # For now, let's re-analyze if asked.
                
                score, reason = analyzer.analyze_row({
                    "company_name": row_data["company"],
                    "reason": row_data["reason"],
                    "return_shares": row_data["shares"],
                    "stake_portion_pct": row_data["stake_pct"],
                    "current_stake_value_million_krw": row_data["value_krw"],
                    "total_shares": 1 # Dummy if needed, logic checks pct/value
                })
                
                # Update DB
                if score is not None:
                    db_item = session.get(SeibroUnstakingSchedule, row_data["id"])
                    if db_item:
                        db_item.block_deal_score = score
                        db_item.block_deal_analysis = reason
                        updated_count += 1
                        
                progress_bar.progress((idx + 1) / len(rows))
            session.commit()
            
        st.success(f"{updated_count}건 분석 완료! 페이지를 새로고침하세요.")
        st.rerun()

    # Data Grid
    st.subheader("상세 목록")
    
    # Color logic for score
    def highlight_score(val):
        if not isinstance(val, (int, float)):
            return ''
        if val >= 80:
            return 'background-color: #ffcccc; color: red; font-weight: bold'
        elif val >= 50:
            return 'background-color: #ffffcc; color: orange'
        return 'color: green'

    # Display columns
    display_df = df[[
        "return_date", "market", "company", "code", 
        "shares", "stake_pct", "value_krw", "reason", 
        "bd_score", "bd_analysis"
    ]].copy()
    
    display_df.columns = [
        "해제일", "시장", "기업명", "종목코드", 
        "반환주식수", "지분율(%)", "평가액(백만)", "해제사유",
        "AI위험도", "분석결과"
    ]
    
    st.dataframe(
        display_df.style.map(highlight_score, subset=["AI위험도"])
                   .format({
                       "반환주식수": "{:,}", 
                       "지분율(%)": "{:.2f}",
                       "평가액(백만)": "{:,.0f}"
                   }),
        use_container_width=True,
        height=600
    )
    
    # Detailed View
    st.divider()
    st.caption("AI 위험도는 0~100점이며, 80점 이상은 블록딜/오버행 우려가 높음을 의미합니다.")
