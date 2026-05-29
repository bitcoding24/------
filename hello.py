import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="전국 학교 망각 위험지수 지도",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Streamlit 기본 여백, 헤더, 사이드바 숨기기
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        display: none;
    }

    [data-testid="stHeader"] {
        display: none;
    }

    [data-testid="stToolbar"] {
        display: none;
    }

    .block-container {
        padding: 0rem !important;
        max-width: 100% !important;
    }

    iframe {
        display: block;
    }
    </style>
    """,
    unsafe_allow_html=True
)

HTML_CODE = r'''
여기에 네 HTML 전체를 그대로 붙여넣기
'''

components.html(
    HTML_CODE,
    height=950,
    scrolling=False
)
