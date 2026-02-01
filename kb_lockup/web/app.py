"""Streamlit main application"""

import streamlit as st

st.set_page_config(
    page_title="KB Lockup",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize session state
if "db_initialized" not in st.session_state:
    st.session_state.db_initialized = False


def main():
    """Main application entry point"""
    st.sidebar.title("🔒 KB Lockup")

    # Navigation - simplified to active tabs only
    page = st.sidebar.selectbox(
        "페이지 선택",
        ["대시보드", "검색"],
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        **KB Lockup**

        한국 상장사 보호예수 일정 추적 시스템

        - DART 공시 데이터 기반
        - 실시간 시장 데이터 연동
        - Excel 내보내기
        """
    )

    # Page routing
    if page == "대시보드":
        from kb_lockup.web.pages.dashboard import render
        render()
    elif page == "검색":
        from kb_lockup.web.pages.search import render
        render()


if __name__ == "__main__":
    main()
