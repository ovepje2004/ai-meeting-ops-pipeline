import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import sqlite3
import json
from collections import Counter
import re

from pipeline.db import DB_PATH

st.set_page_config(
    page_title="Meeting Pipeline Dashboard",
    page_icon="📋",
    layout="wide",
)

# ── DB 로딩 헬퍼 ─────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_data():
    if not DB_PATH.exists():
        return {}, {}, {}, {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    meetings = pd.read_sql("SELECT * FROM meetings", conn)
    action_items = pd.read_sql("SELECT * FROM action_items", conn)
    logs = pd.read_sql("SELECT * FROM llm_extraction_logs", conn)
    utterances = pd.read_sql("SELECT * FROM utterances_processed", conn)
    conn.close()
    return meetings, action_items, logs, utterances


# ── 사이드바 ─────────────────────────────────────────────────
st.sidebar.title("📋 Meeting Pipeline")
st.sidebar.markdown("---")

meetings_df, items_df, logs_df, utt_df = load_data()

if meetings_df is None or len(meetings_df) == 0:
    st.warning("데이터가 없습니다. 먼저 `make run`으로 파이프라인을 실행해주세요.")
    st.code("make run", language="bash")
    st.stop()

# 날짜 처리
items_df["extracted_at"] = pd.to_datetime(items_df["extracted_at"], errors="coerce")
meetings_df["meeting_date"] = pd.to_datetime(meetings_df["meeting_date"], errors="coerce")
items_df["week"] = items_df["extracted_at"].dt.to_period("W").astype(str)

# 필터
advertiser_list = ["전체"] + sorted(meetings_df["advertiser"].unique().tolist())
selected_advertiser = st.sidebar.selectbox("광고주 필터", advertiser_list)

if selected_advertiser != "전체":
    filtered_items = items_df[items_df["advertiser"] == selected_advertiser]
    filtered_meetings = meetings_df[meetings_df["advertiser"] == selected_advertiser]
else:
    filtered_items = items_df
    filtered_meetings = meetings_df

st.sidebar.markdown("---")
st.sidebar.metric("총 회의 수", len(filtered_meetings))
st.sidebar.metric("총 액션아이템", len(filtered_items))
pending = len(filtered_items[filtered_items["status"] == "pending"])
st.sidebar.metric("미완료 항목", pending)

# ── 메인 타이틀 ──────────────────────────────────────────────
st.title("📋 회의 분석 대시보드")
st.markdown(f"광고주: **{selected_advertiser}** | 마지막 갱신: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
st.markdown("---")

# ════════════════════════════════════════════════════════════
# Widget 1: 주차별 회의·액션아이템 발생 추이
# ════════════════════════════════════════════════════════════
st.subheader("📈 위젯 1 — 주차별 회의·액션아이템 발생 추이")
st.caption("의사결정자가 '언제 어느 주에 부하가 집중됐는지' 파악하는 뷰")

col1, col2 = st.columns(2)

with col1:
    # 주차별 회의 수
    if "meeting_date" in filtered_meetings.columns and not filtered_meetings.empty:
        mtg_week = filtered_meetings.copy()
        mtg_week["week"] = mtg_week["meeting_date"].dt.to_period("W").astype(str)
        mtg_cnt = mtg_week.groupby("week").size().reset_index(name="회의 수")
        st.bar_chart(mtg_cnt.set_index("week")["회의 수"])
        st.caption("주차별 회의 수")

with col2:
    # 주차별 액션아이템 수
    if not filtered_items.empty and "week" in filtered_items.columns:
        act_cnt = filtered_items.groupby("week").size().reset_index(name="액션아이템 수")
        st.bar_chart(act_cnt.set_index("week")["액션아이템 수"])
        st.caption("주차별 액션아이템 수")

st.markdown("---")

# ════════════════════════════════════════════════════════════
# Widget 2: 담당자별 미완료 액션아이템 Top N
# ════════════════════════════════════════════════════════════
st.subheader("👤 위젯 2 — 담당자별 미완료 액션아이템 Top N")
st.caption("누가 가장 많은 미완료 항목을 보유하고 있는지 → 업무 과부하 조기 감지")

pending_items = filtered_items[filtered_items["status"] == "pending"]

if not pending_items.empty:
    top_n = st.slider("Top N", min_value=3, max_value=10, value=5)
    assignee_cnt = (
        pending_items.groupby(["assignee", "assignee_role"])
        .size()
        .reset_index(name="미완료 수")
        .sort_values("미완료 수", ascending=False)
        .head(top_n)
    )
    assignee_cnt["담당자"] = assignee_cnt["assignee"] + "\n(" + assignee_cnt["assignee_role"] + ")"

    st.bar_chart(assignee_cnt.set_index("담당자")["미완료 수"])

    # 드릴다운: 담당자 선택 시 해당 액션아이템 목록 표시
    selected_person = st.selectbox(
        "담당자 선택 → 상세 보기",
        ["선택하세요"] + assignee_cnt["assignee"].tolist()
    )
    if selected_person != "선택하세요":
        detail = pending_items[pending_items["assignee"] == selected_person][
            ["title", "description", "due_date", "priority", "confidence"]
        ]
        st.dataframe(detail, use_container_width=True)
else:
    st.info("미완료 액션아이템이 없습니다.")

st.markdown("---")

# ════════════════════════════════════════════════════════════
# Widget 3: 캠페인/광고주별 반복 이슈 키워드
# ════════════════════════════════════════════════════════════
st.subheader("🔑 위젯 3 — 반복 이슈 키워드 (BoW 기반)")
st.caption("어떤 주제가 회의마다 반복적으로 등장하는지 → 구조적 문제 식별")

STOPWORDS = {
    "있어요", "해요", "이요", "거요", "됩니다", "하고", "이랑", "에서",
    "으로", "에도", "하는", "있는", "것을", "이번", "다음", "그냥",
    "좀", "더", "그", "이", "저", "우리", "네", "아", "어", "음",
    "것", "수", "할", "해", "한", "및", "또", "안", "못", "잖아요",
}

def extract_keywords(texts: list[str], top_k: int = 20) -> dict[str, int]:
    word_counter: Counter = Counter()
    for text in texts:
        if not isinstance(text, str):
            continue
        words = re.findall(r"[가-힣a-zA-Z]{2,}", text)
        for w in words:
            if w not in STOPWORDS and len(w) >= 2:
                word_counter[w] += 1
    return dict(word_counter.most_common(top_k))

if not filtered_items.empty:
    all_texts = filtered_items["description"].tolist() + filtered_items["title"].tolist()
    keywords = extract_keywords(all_texts)
    if keywords:
        kw_df = pd.DataFrame(list(keywords.items()), columns=["키워드", "빈도"])
        st.bar_chart(kw_df.set_index("키워드")["빈도"])
    else:
        st.info("키워드를 추출할 데이터가 부족합니다.")

    # 광고주/캠페인별 breakdown
    if "advertiser" in filtered_items.columns:
        for adv in filtered_items["advertiser"].dropna().unique():
            with st.expander(f"📌 {adv} 키워드"):
                adv_texts = filtered_items[filtered_items["advertiser"] == adv]["description"].tolist()
                kw = extract_keywords(adv_texts, top_k=10)
                if kw:
                    st.bar_chart(pd.DataFrame(list(kw.items()), columns=["키워드", "빈도"]).set_index("키워드"))

st.markdown("---")

# ════════════════════════════════════════════════════════════
# Widget 4: LLM confidence 분포 + 낮은 항목 드릴다운
# ════════════════════════════════════════════════════════════
st.subheader("🤖 위젯 4 — LLM Confidence 분포 & 낮은 항목 드릴다운")
st.caption("추출 신뢰도가 낮은 항목 = 사람이 검수해야 하는 항목")

if not filtered_items.empty:
    col_a, col_b, col_c = st.columns(3)
    high = len(filtered_items[filtered_items["confidence"] >= 0.8])
    mid  = len(filtered_items[(filtered_items["confidence"] >= 0.5) & (filtered_items["confidence"] < 0.8)])
    low  = len(filtered_items[filtered_items["confidence"] < 0.5])

    col_a.metric("✅ High (≥0.8)", high)
    col_b.metric("⚠️  Medium (0.5~0.79)", mid)
    col_c.metric("❓ Low (<0.5)", low)

    # 히스토그램
    hist_data = filtered_items["confidence"].dropna()
    bins = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    labels = [f"{int(b*10)*10}~{int(b*10)*10+10}%" for b in bins[:-1]]
    counts = pd.cut(hist_data, bins=bins, labels=labels).value_counts().sort_index()
    st.bar_chart(counts)

    # 드릴다운: 낮은 confidence 항목
    threshold = st.slider("검수 필요 임계값 (이하)", 0.0, 1.0, 0.7, 0.05)
    low_conf = filtered_items[filtered_items["confidence"] <= threshold].sort_values("confidence")

    if not low_conf.empty:
        st.markdown(f"**검수 필요 항목 {len(low_conf)}건** (confidence ≤ {threshold:.0%})")
        display_cols = ["title", "assignee", "confidence", "source_quote", "due_date"]
        available = [c for c in display_cols if c in low_conf.columns]
        st.dataframe(
            low_conf[available].rename(columns={
                "title": "액션아이템",
                "assignee": "담당자",
                "confidence": "신뢰도",
                "source_quote": "원문 인용",
                "due_date": "기한",
            }),
            use_container_width=True,
        )
    else:
        st.success(f"임계값 {threshold:.0%} 이하 항목 없음 ✅")

# ── LLM 추출 로그 ────────────────────────────────────────────
if not logs_df.empty:
    with st.expander("🔧 LLM 추출 로그 (재시도 이력)"):
        st.dataframe(logs_df[["meeting_id", "attempt", "model", "success", "error_message", "created_at"]])