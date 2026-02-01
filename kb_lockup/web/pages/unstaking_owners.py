
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from sqlalchemy import select, desc

from kb_lockup.db.engine import get_db_session
from kb_lockup.models.orm import SeibroUnstakingSchedule, UnstakingOwner

def render():
    st.title("👥 주요 주주 의무보유 해제 (Owners View)")
    
    st.info("AI 매칭 또는 수동으로 식별된 소유자들의 해제 일정입니다.")
    
    rows = []
    with get_db_session() as session:
        # Join Owner -> Schedule
        # We want to see: Owner Name | Company | Release Date | Shares | Value | Confidence
        
        query = session.query(
            UnstakingOwner, SeibroUnstakingSchedule
        ).join(
            SeibroUnstakingSchedule, UnstakingOwner.schedule_id == SeibroUnstakingSchedule.id
        ).filter(
            SeibroUnstakingSchedule.return_date >= date.today()
        ).order_by(
            SeibroUnstakingSchedule.return_date.asc()
        )
        
        results = query.all()
        
        for owner, schedule in results:
            # Estimate value if shares match
            # If owner.shares is DART holding, it might differ from unstaking shares.
            # But roughly:
            val = 0
            if schedule.stock_current_price_krw and owner.shares:
                val = (owner.shares * float(schedule.stock_current_price_krw)) / 1_000_000
                
            rows.append({
                "owner": owner.owner_name,
                "company": schedule.company_name,
                "date": schedule.return_date,
                "shares": owner.shares,
                "value_krw": val,
                "confidence": owner.confidence,
                "source": owner.match_source,
                "is_manual": "✅" if owner.is_manual else ""
            })
            
    if not rows:
        st.warning("식별된 소유자 데이터가 없습니다. Dashboard에서 'O' 버튼을 눌러 매칭을 수행하세요.")
        return
        
    df = pd.DataFrame(rows)
    
    st.dataframe(
        df[[
            "date", "owner", "company", "shares", "value_krw", "confidence", "is_manual" 
        ]].style.format({
            "shares": "{:,}",
            "value_krw": "{:,.0f}M",
            "confidence": "{:.2f}"
        }),
        use_container_width=True,
        height=700
    )
