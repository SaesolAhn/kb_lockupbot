"""Streamlit main application"""

import streamlit as st

from kb_lockup.web.utils import run_async

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
        ["대시보드 (Unstaking)", "데이터 관리"],
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        **KB Lockup**

        SEIBro 기반 의무보유 현황 대시보드

        - AI 블록딜 위험 분석
        - 실시간 주가 연동
        """
    )

    # Page routing
    # Page routing
    if "대시보드" in page:
        from kb_lockup.web.pages.unstaking_dashboard import render
        render()
    elif page == "데이터 관리":
        render_admin()


def render_admin():
    """Admin/management page"""
    st.title("⚙️ 관리")

    st.header("데이터베이스")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📦 데이터베이스 초기화"):
            from kb_lockup.storage.database import Database

            async def init_db():
                async with Database() as db:
                    await db.init_schema()

            try:
                run_async(init_db())
                st.success("데이터베이스가 초기화되었습니다.")
                st.session_state.db_initialized = True
            except Exception as e:
                st.error(f"초기화 실패: {e}")

    with col2:
        if st.button("🗑️ 캐시 삭제"):
            from kb_lockup.storage.cache import Cache

            async def clear_cache():
                async with Cache() as cache:
                    return await cache.clear_all()

            try:
                count = run_async(clear_cache())
                st.success(f"{count}개의 캐시 항목이 삭제되었습니다.")
            except Exception as e:
                st.error(f"캐시 삭제 실패: {e}")

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
