import re
import json
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import pydeck as pdk


# =========================================================
# 1. 여기에 네 기존 HTML 전체를 그대로 붙여넣기
# =========================================================
# 기존 HTML 전체를 아래 r'''  ''' 사이에 붙여넣으면 됩니다.
# const DATA = {...}; 가 포함되어 있으면 앱이 자동으로 DATA만 추출합니다.

EMBEDDED_HTML_OR_DATA = r'''
여기에_기존_HTML_전체를_붙여넣으세요
'''


# =========================================================
# 2. DATA 추출 함수
# =========================================================

def extract_data_object(text: str) -> dict:
    """
    기존 HTML 안의 `const DATA = {...};` 부분을 찾아 Python dict로 변환.
    또는 DATA 객체 자체만 붙여넣어도 처리.
    """
    text = text.strip()

    if text.startswith("{") and text.endswith("}"):
        raw = text
    else:
        match = re.search(r"const\s+DATA\s*=\s*(\{.*?\});", text, flags=re.S)
        if not match:
            st.error("코드 안에서 `const DATA = {...};`를 찾지 못했습니다.")
            st.stop()
        raw = match.group(1)

    try:
        return json.loads(raw)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception as e:
            st.error("DATA를 파싱하지 못했습니다. HTML 안의 const DATA 부분이 깨졌을 수 있습니다.")
            st.exception(e)
            st.stop()


def is_number_list(values):
    if not isinstance(values, list) or len(values) == 0:
        return False
    sample = values[: min(len(values), 100)]
    try:
        [float(x) for x in sample if x is not None]
        return True
    except Exception:
        return False


def detect_array_key(data, n, candidates):
    for key in candidates:
        if key in data and isinstance(data[key], list) and len(data[key]) == n:
            return key
    return None


def detect_lat_lon_keys(data, n):
    numeric_keys = [
        k for k, v in data.items()
        if isinstance(v, list) and len(v) == n and is_number_list(v)
    ]

    lat_key = None
    lon_key = None

    for k in numeric_keys:
        arr = pd.to_numeric(pd.Series(data[k]), errors="coerce")
        valid_ratio = arr.between(32, 39).mean()
        if valid_ratio > 0.8:
            lat_key = k
            break

    for k in numeric_keys:
        if k == lat_key:
            continue
        arr = pd.to_numeric(pd.Series(data[k]), errors="coerce")
        valid_ratio = arr.between(124, 132).mean()
        if valid_ratio > 0.8:
            lon_key = k
            break

    return lat_key, lon_key


def detect_course_key(data, n):
    candidates = ["course", "school_course", "학교과정", "학교과정명", "c", "type", "t"]
    key = detect_array_key(data, n, candidates)

    if key:
        return key

    for k, v in data.items():
        if not isinstance(v, list) or len(v) != n:
            continue

        s = pd.Series(v)
        unique = set(s.dropna().astype(str).unique())

        if unique.issubset({"0", "1", "2", "초", "중", "고", "초등학교", "중학교", "고등학교"}):
            return k

    return None


def detect_sido_key(data, n):
    """
    DATA.sido가 17개 교육청 이름 목록이고,
    다른 배열 하나가 각 학교의 시도 인덱스일 가능성을 탐지.
    """
    sido_lookup = data.get("sido", None)

    if isinstance(sido_lookup, list) and len(sido_lookup) < n:
        for k, v in data.items():
            if not isinstance(v, list) or len(v) != n:
                continue

            s = pd.to_numeric(pd.Series(v), errors="coerce")
            if s.notna().mean() > 0.9 and s.min() >= 0 and s.max() < len(sido_lookup):
                return k, sido_lookup

    direct_candidates = ["시도교육청명", "sido_name", "region", "교육청"]
    key = detect_array_key(data, n, direct_candidates)

    if key:
        return key, None

    return None, sido_lookup


def detect_risk_key(data, n, exclude_keys):
    priority = [
        "최종위험지수", "risk", "risk_score", "final_risk",
        "score", "r", "v"
    ]

    for key in priority:
        if key in data and key not in exclude_keys:
            if isinstance(data[key], list) and len(data[key]) == n and is_number_list(data[key]):
                return key

    numeric_keys = [
        k for k, v in data.items()
        if k not in exclude_keys
        and isinstance(v, list)
        and len(v) == n
        and is_number_list(v)
    ]

    # 위도/경도, 과정, 시도 인덱스를 제외한 숫자 배열 중
    # 값 범위가 위험지수처럼 보이는 것을 선택
    for k in numeric_keys:
        arr = pd.to_numeric(pd.Series(data[k]), errors="coerce")
        if arr.notna().mean() > 0.8 and arr.min() >= 0 and arr.max() <= 100:
            return k

    return numeric_keys[0] if numeric_keys else None


def detect_percentile_key(data, n, exclude_keys):
    candidates = ["위험백분위", "percentile", "pct", "p", "rank_pct"]

    for key in candidates:
        if key in data and key not in exclude_keys:
            if isinstance(data[key], list) and len(data[key]) == n and is_number_list(data[key]):
                return key

    return None


def convert_to_dataframe(data: dict) -> pd.DataFrame:
    """
    압축된 JS DATA 구조를 Streamlit용 DataFrame으로 변환.
    """
    name_key = detect_array_key(data, None, [])  # 사용하지 않음

    if "n" in data:
        name_key = "n"
    elif "name" in data:
        name_key = "name"
    elif "학교명" in data:
        name_key = "학교명"
    else:
        st.error("학교명 배열을 찾지 못했습니다. DATA 안에 `n`, `name`, `학교명` 중 하나가 필요합니다.")
        st.stop()

    n = len(data[name_key])

    lat_key, lon_key = detect_lat_lon_keys(data, n)

    if lat_key is None or lon_key is None:
        st.error("위도/경도 배열을 자동으로 찾지 못했습니다. DATA 안에 한국 위도(33~39), 경도(124~132) 값이 필요합니다.")
        st.write("DATA 키 목록:", list(data.keys()))
        st.stop()

    course_key = detect_course_key(data, n)
    sido_key, sido_lookup = detect_sido_key(data, n)

    exclude_keys = {name_key, lat_key, lon_key}
    if course_key:
        exclude_keys.add(course_key)
    if sido_key:
        exclude_keys.add(sido_key)

    risk_key = detect_risk_key(data, n, exclude_keys)
    if risk_key:
        exclude_keys.add(risk_key)

    pct_key = detect_percentile_key(data, n, exclude_keys)

    df = pd.DataFrame({
        "학교명": data[name_key],
        "위도": pd.to_numeric(pd.Series(data[lat_key]), errors="coerce"),
        "경도": pd.to_numeric(pd.Series(data[lon_key]), errors="coerce"),
    })

    if risk_key:
        df["위험지수"] = pd.to_numeric(pd.Series(data[risk_key]), errors="coerce")
    else:
        df["위험지수"] = np.nan

    if pct_key:
        df["위험백분위"] = pd.to_numeric(pd.Series(data[pct_key]), errors="coerce")
    else:
        if df["위험지수"].notna().any():
            df["위험백분위"] = df["위험지수"].rank(pct=True) * 100
        else:
            df["위험백분위"] = np.nan

    if course_key:
        course_raw = pd.Series(data[course_key]).astype(str)

        course_map = {
            "0": "초등학교",
            "1": "중학교",
            "2": "고등학교",
            "초": "초등학교",
            "중": "중학교",
            "고": "고등학교",
            "초등": "초등학교",
            "중등": "중학교",
            "고등": "고등학교",
        }

        df["학교과정명"] = course_raw.map(course_map).fillna(course_raw)
    else:
        # 학교명 끝 글자로 추정
        def infer_course(name):
            name = str(name)
            if "초등학교" in name or name.endswith("초등학교") or name.endswith("초"):
                return "초등학교"
            if "중학교" in name or name.endswith("중학교") or name.endswith("중"):
                return "중학교"
            if "고등학교" in name or name.endswith("고등학교") or name.endswith("고"):
                return "고등학교"
            return "기타"

        df["학교과정명"] = df["학교명"].apply(infer_course)

    if sido_key:
        sido_values = pd.Series(data[sido_key])

        if sido_lookup is not None:
            df["시도교육청명"] = sido_values.astype(int).map(lambda x: sido_lookup[x] if 0 <= x < len(sido_lookup) else "")
        else:
            df["시도교육청명"] = sido_values.astype(str)
    else:
        df["시도교육청명"] = "미상"

    df = df.dropna(subset=["위도", "경도"]).copy()

    df["위험지수"] = df["위험지수"].fillna(0).astype(float)
    df["위험백분위"] = df["위험백분위"].fillna(df["위험지수"].rank(pct=True) * 100)

    df["표시명"] = (
        df["학교명"].astype(str)
        + " · "
        + df["학교과정명"].astype(str)
        + " · "
        + df["시도교육청명"].astype(str)
    )

    return df


def risk_grade(pct):
    if pct >= 95:
        return "매우 높음"
    if pct >= 80:
        return "높음"
    if pct >= 50:
        return "보통"
    if pct >= 20:
        return "낮음"
    return "매우 낮음"


def add_map_style_columns(df):
    out = df.copy()

    out["상대위험등급"] = out["위험백분위"].apply(risk_grade)

    # PyDeck 색상용 RGB
    def color_by_pct(p):
        if p >= 95:
            return [220, 38, 38, 210]
        if p >= 80:
            return [245, 158, 11, 205]
        if p >= 50:
            return [234, 179, 8, 195]
        if p >= 20:
            return [34, 197, 94, 190]
        return [59, 130, 246, 180]

    out["color"] = out["위험백분위"].apply(color_by_pct)

    # 점 크기
    out["radius"] = 55 + out["위험백분위"].fillna(0) * 1.2

    return out


@st.cache_data
def load_embedded_data():
    data = extract_data_object(EMBEDDED_HTML_OR_DATA)
    df = convert_to_dataframe(data)
    df = add_map_style_columns(df)
    return df


# =========================================================
# 3. Streamlit 화면
# =========================================================

st.set_page_config(
    page_title="전국 학교 망각 위험지수 지도",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("전국 학교 망각 위험지수 지도")
st.caption("Streamlit 버전 · HTML 지도 사용 안 함 · 데이터는 app.py 코드 안에 내장")

df = load_embedded_data()

with st.sidebar:
    st.header("검색 및 필터")

    query = st.text_input("학교명 검색", placeholder="예: 부설, 대구일과학, 서울")

    course_options = ["전체"] + sorted(df["학교과정명"].dropna().unique().tolist())
    selected_course = st.selectbox("학교급", course_options)

    sido_options = ["전체"] + sorted(df["시도교육청명"].dropna().unique().tolist())
    selected_sido = st.selectbox("시도교육청", sido_options)

    color_mode = st.radio(
        "지도 색상 기준",
        ["위험백분위", "위험지수"],
        horizontal=True,
    )

    min_pct, max_pct = st.slider(
        "위험백분위 범위",
        min_value=0.0,
        max_value=100.0,
        value=(0.0, 100.0),
        step=1.0,
    )

filtered = df.copy()

if query.strip():
    q = query.strip()
    filtered = filtered[
        filtered["학교명"].str.contains(q, case=False, na=False)
        | filtered["시도교육청명"].str.contains(q, case=False, na=False)
    ]

if selected_course != "전체":
    filtered = filtered[filtered["학교과정명"] == selected_course]

if selected_sido != "전체":
    filtered = filtered[filtered["시도교육청명"] == selected_sido]

filtered = filtered[
    (filtered["위험백분위"] >= min_pct)
    & (filtered["위험백분위"] <= max_pct)
].copy()

if len(filtered) == 0:
    st.warning("조건에 맞는 학교가 없습니다.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("표시 학교 수", f"{len(filtered):,}")
c2.metric("전체 학교 수", f"{len(df):,}")
c3.metric("평균 위험지수", f"{filtered['위험지수'].mean():.2f}")
c4.metric("평균 위험백분위", f"{filtered['위험백분위'].mean():.1f}")

# 검색 추천
if query.strip():
    st.subheader("검색 추천")
    suggestion = filtered.sort_values("위험백분위", ascending=False).head(30).copy()
    selected_label = st.selectbox(
        "추천 학교 선택",
        suggestion["표시명"].tolist(),
    )
    selected_school = suggestion[suggestion["표시명"] == selected_label].iloc[0]
else:
    selected_school = filtered.sort_values("위험백분위", ascending=False).iloc[0]

# 지도 중심
center_lat = float(filtered["위도"].mean())
center_lon = float(filtered["경도"].mean())

view_state = pdk.ViewState(
    latitude=center_lat,
    longitude=center_lon,
    zoom=7,
    pitch=0,
)

tooltip = {
    "html": """
    <b>{학교명}</b><br/>
    {시도교육청명} · {학교과정명}<br/>
    위험지수: <b>{위험지수}</b><br/>
    위험백분위: <b>{위험백분위}</b><br/>
    상대등급: <b>{상대위험등급}</b>
    """,
    "style": {
        "backgroundColor": "#1d2735",
        "color": "white",
    },
}

layer = pdk.Layer(
    "ScatterplotLayer",
    data=filtered,
    get_position="[경도, 위도]",
    get_fill_color="color",
    get_radius="radius",
    pickable=True,
    auto_highlight=True,
)

deck = pdk.Deck(
    map_style="mapbox://styles/mapbox/dark-v10",
    initial_view_state=view_state,
    layers=[layer],
    tooltip=tooltip,
)

st.pydeck_chart(deck, use_container_width=True)

st.divider()

st.subheader("선택 학교 상세")

if query.strip():
    detail_row = selected_school
else:
    top_df = filtered.sort_values("위험백분위", ascending=False).head(100).copy()
    detail_label = st.selectbox(
        "상세 정보를 볼 학교",
        top_df["표시명"].tolist(),
    )
    detail_row = top_df[top_df["표시명"] == detail_label].iloc[0]

d1, d2, d3, d4 = st.columns(4)
d1.metric("학교명", detail_row["학교명"])
d2.metric("위험지수", f"{detail_row['위험지수']:.2f}")
d3.metric("위험백분위", f"{detail_row['위험백분위']:.1f}%")
d4.metric("상대위험등급", detail_row["상대위험등급"])

st.write(
    {
        "시도교육청": detail_row["시도교육청명"],
        "학교과정": detail_row["학교과정명"],
        "위도": round(float(detail_row["위도"]), 6),
        "경도": round(float(detail_row["경도"]), 6),
    }
)

st.subheader("표 데이터")
show_cols = [
    "학교명",
    "학교과정명",
    "시도교육청명",
    "위험지수",
    "위험백분위",
    "상대위험등급",
    "위도",
    "경도",
]
st.dataframe(
    filtered[show_cols].sort_values("위험백분위", ascending=False),
    use_container_width=True,
    height=420,
)
