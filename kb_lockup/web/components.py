"""Reusable Streamlit components"""

from datetime import date
from typing import List, Optional

import streamlit as st

from kb_lockup.core.models import LockupData


def lockup_card(data: LockupData) -> None:
    """Display a lockup entry as a card"""
    with st.container():
        st.markdown(
            f"""
            <div style="
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 16px;
                margin: 8px 0;
            ">
                <h4>{data.company_name}</h4>
                <p><strong>주주:</strong> {data.owner}</p>
                <p><strong>보유량:</strong> {data.amount:,}주 ({data.ratio:.1f}%)</p>
                <p><strong>해제일:</strong> {data.release_date}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def metric_card(label: str, value: str, delta: Optional[str] = None) -> None:
    """Display a metric card"""
    st.metric(label=label, value=value, delta=delta)


def company_selector(
    companies: List[str],
    key: str = "company_select",
) -> Optional[str]:
    """Company selection dropdown"""
    return st.selectbox(
        "회사 선택",
        options=[""] + companies,
        format_func=lambda x: "회사를 선택하세요" if x == "" else x,
        key=key,
    ) or None


def date_range_selector(
    key_prefix: str = "date",
    default_days: int = 30,
) -> tuple:
    """Date range selection"""
    col1, col2 = st.columns(2)

    with col1:
        start = st.date_input(
            "시작일",
            value=date.today(),
            key=f"{key_prefix}_start",
        )

    with col2:
        from datetime import timedelta
        end = st.date_input(
            "종료일",
            value=date.today() + timedelta(days=default_days),
            key=f"{key_prefix}_end",
        )

    return start, end


def progress_bar(current: int, total: int, label: str = "") -> None:
    """Display progress bar"""
    progress = current / total if total > 0 else 0
    st.progress(progress, text=f"{label} {current}/{total}")


def data_table(
    data: List[dict],
    columns: Optional[List[str]] = None,
) -> None:
    """Display data as a table"""
    import pandas as pd

    df = pd.DataFrame(data)

    if columns:
        df = df[columns]

    st.dataframe(df, use_container_width=True, hide_index=True)


def empty_state(message: str, icon: str = "📭") -> None:
    """Display empty state message"""
    st.markdown(
        f"""
        <div style="
            text-align: center;
            padding: 40px;
            color: #888;
        ">
            <div style="font-size: 48px;">{icon}</div>
            <p>{message}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def confirm_dialog(message: str, key: str) -> bool:
    """Display confirmation dialog"""
    with st.expander("확인", expanded=True):
        st.warning(message)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("확인", key=f"{key}_confirm"):
                return True
        with col2:
            if st.button("취소", key=f"{key}_cancel"):
                st.rerun()
    return False
