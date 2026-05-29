import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

st.set_page_config(
    page_title="전국 학교 망각 위험지수 지도",
    layout="wide"
)

st.title("전국 학교 망각 위험지수 지도")

html_path = Path("map.html")

if not html_path.exists():
    st.error("map.html 파일을 찾을 수 없습니다. app.py와 같은 폴더에 map.html을 넣어주세요.")
    st.stop()

html = html_path.read_text(encoding="utf-8")

components.html(
    html,
    height=900,
    scrolling=False
)
