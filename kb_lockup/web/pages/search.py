"""Search page - search and filter lockup data"""

from datetime import date

import streamlit as st
import pandas as pd

from kb_lockup.storage.database import Database
from kb_lockup.export.excel import ExcelExporter
from kb_lockup.web.utils import run_async


def render():
    """Render search page"""
    st.title("🔍 보호예수 검색")

    # Search form
    col1, col2 = st.columns([3, 1])

    with col1:
        query = st.text_input(
            "검색어",
            placeholder="회사명 또는 종목코드 입력",
            key="search_query",
        )

    with col2:
        search_button = st.button("검색", type="primary", use_container_width=True)

    # Filters
    with st.expander("🔧 필터 옵션"):
        col1, col2, col3 = st.columns(3)

        with col1:
            min_ratio = st.number_input(
                "최소 지분율 (%)",
                min_value=0.0,
                max_value=100.0,
                value=0.0,
                step=0.5,
            )

        with col2:
            days_range = st.slider(
                "해제일 범위 (일)",
                min_value=0,
                max_value=365,
                value=(0, 90),
            )

        with col3:
            sort_by = st.selectbox(
                "정렬 기준",
                ["해제일", "지분율", "보유량"],
            )

    # Perform search
    if search_button or query:
        results = run_async(search_lockups(query, min_ratio))

        if not results:
            st.warning("검색 결과가 없습니다.")
            return

        # Filter by date range
        filtered = [
            r for r in results
            if r.release_date and days_range[0] <= (r.release_date - date.today()).days <= days_range[1]
        ] if any(r.release_date for r in results) else results

        st.success(f"{len(filtered)}건의 결과를 찾았습니다.")

        # Convert to DataFrame
        df = pd.DataFrame([
            {
                "회사명": lockup.company_name,
                "종목코드": lockup.stock_code or "-",
                "주주명": lockup.owner,
                "보유량": lockup.amount,
                "지분율(%)": lockup.ratio,
                "해제일": lockup.release_date.isoformat() if lockup.release_date else "-",
                "D-Day": (lockup.release_date - date.today()).days if lockup.release_date else None,
                "비고": lockup.remarks or "-",
            }
            for lockup in filtered
        ])

        # Sort
        sort_map = {
            "해제일": "해제일",
            "지분율": "지분율(%)",
            "보유량": "보유량",
        }
        if sort_by and sort_map[sort_by] in df.columns:
            ascending = sort_by == "해제일"
            df = df.sort_values(sort_map[sort_by], ascending=ascending, na_position="last")

        # Display results
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "보유량": st.column_config.NumberColumn(format="%d"),
                "지분율(%)": st.column_config.NumberColumn(format="%.2f"),
                "D-Day": st.column_config.NumberColumn(format="%d일"),
            },
        )

        # Export button
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("📥 Excel 내보내기"):
                exporter = ExcelExporter()
                filepath = exporter.export_lockup_data(filtered)
                st.success(f"파일 저장: {filepath}")

                with open(filepath, "rb") as f:
                    st.download_button(
                        "다운로드",
                        data=f,
                        file_name=filepath.name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )


async def search_lockups(query: str, min_ratio: float = 0.0) -> list:
    """Search lockup data"""
    try:
        async with Database() as db:
            results = await db.search_lockup(query)

            # Filter by min ratio
            if min_ratio > 0:
                results = [r for r in results if r.ratio and r.ratio >= min_ratio]

            return results
    except Exception as e:
        st.error(f"검색 실패: {e}")
        return []
