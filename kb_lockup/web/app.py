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

    # Navigation
    page = st.sidebar.selectbox(
        "페이지 선택",
        ["대시보드", "검색", "분석", "관리"],
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        **KB Lockup**

        한국 상장사 보호예수 일정 추적 시스템

        - DART 공시 데이터 기반
        - 실시간 알림 지원
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
    elif page == "분석":
        from kb_lockup.web.pages.analysis import render
        render()
    elif page == "관리":
        render_admin()


def render_admin():
    """Admin/management page"""
    st.title("⚙️ 관리")

    st.header("데이터베이스")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📦 데이터베이스 초기화"):
            import asyncio
            from kb_lockup.storage.database import Database

            async def init_db():
                async with Database() as db:
                    await db.init_schema()

            asyncio.run(init_db())
            st.success("데이터베이스가 초기화되었습니다.")
            st.session_state.db_initialized = True

    with col2:
        if st.button("🗑️ 캐시 삭제"):
            import asyncio
            from kb_lockup.storage.cache import Cache

            async def clear_cache():
                async with Cache() as cache:
                    return await cache.clear_all()

            count = asyncio.run(clear_cache())
            st.success(f"{count}개의 캐시 항목이 삭제되었습니다.")

    st.header("추출 작업")

    company_input = st.text_input("회사명 입력")
    if st.button("🔍 DART에서 추출") and company_input:
        st.info(f"'{company_input}' 추출 작업 시작...")
        # TODO: Implement extraction
        st.warning("추출 기능은 아직 구현되지 않았습니다.")

    st.header("시스템 정보")

    from kb_lockup.config import settings

    st.json({
        "db_path": str(settings.db_path),
        "export_dir": str(settings.export_dir),
        "dart_api_key": "설정됨" if settings.dart_api_key else "미설정",
        "qwen_api_key": "설정됨" if settings.qwen_api_key else "미설정",
        "telegram_token": "설정됨" if settings.telegram_bot_token else "미설정",
    })


if __name__ == "__main__":
    main()
