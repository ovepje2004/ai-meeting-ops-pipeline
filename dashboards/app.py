import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import sqlite3
from collections import Counter
import re
import plotly.express as px
import plotly.graph_objects as go

from pipeline.db import DB_PATH

# ─────────────────────────────────────────────
# 🎨 UI CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Meeting Intelligence",
    page_icon="📊",
    layout="wide",
)

# 토스(Toss) 다크모드 인앱 스타일 CSS 고도화 (맥 스타일 고딕 폰트 매핑)
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
    
    html, body, [data-testid="stAppViewContainer"] {
        font-family: "SF Pro Display", "-apple-system", "BlinkMacSystemFont", "Pretendard", "Apple SD Gothic Neo", sans-serif;
        background-color: #101826 !important;
        color: #FFFFFF !important; /* [변경] 기본 본문 글씨를 화이트로 변경 */
    }
    .main {
        background-color: #101826;
    }
    .block-container {
        padding-top: 1.5rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    h1, h2, h3, h4 {
        color: #ffffff !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em !important;
    }
    
    /* 📌 필터 컴포넌트(Selectbox, Slider) 라벨 글씨 화이트로 */
    label[data-testid="stWidgetLabel"] p {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    
    /* 토스형 미니멀 KPI 카드 리디자인 */
    div[data-testid="metric-container"] {
        background: #172131;
        border: 1px solid #223147;
        padding: 22px;
        border-radius: 16px;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.15);
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-3px);
        border-color: #0064ff;
        box-shadow: 0 12px 24px rgba(0, 100, 255, 0.15);
    }
    
    /* 📌 KPI 숫자 크고 선명한 화이트로 고정 */
    div[data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 26px !important;
        font-weight: 700 !important;
    }
    
    /* 📌 KPI 설명 라벨을 기존 어두운 회색에서 밝은 회색으로 변경 */
    div[data-testid="stMetricLabel"] {
        color: #f1f5f9 !important;
        font-size: 14px !important;
        font-weight: 500 !important;
    }
    
    /* 토스 세그먼트형 Tab 디자인 커스텀 */
    button[data-baseweb="tab"] {
        font-size: 15px !important;
        font-weight: 600 !important;
        color: #94a3b8 !important; /* [변경] 선택되지 않은 탭도 좀 더 밝게 */
        padding: 12px 16px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #0064ff !important;
        border-bottom-color: #0064ff !important;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 📦 DATA LOADING
# ─────────────────────────────────────────────
@st.cache_data(ttl=30)
def load_data():
    if not DB_PATH.exists():
        return None, None, None, None

    conn = sqlite3.connect(DB_PATH)
    meetings = pd.read_sql("SELECT * FROM meetings", conn)
    action_items = pd.read_sql("SELECT * FROM action_items", conn)
    logs = pd.read_sql("SELECT * FROM llm_extraction_logs", conn)
    utterances = pd.read_sql("SELECT * FROM utterances_processed", conn)
    conn.close()
    
    return meetings, action_items, logs, utterances

meetings_df, items_df, logs_df, utt_df = load_data()

if meetings_df is None or len(meetings_df) == 0:
    st.warning("데이터가 없습니다. `make run`을 먼저 실행해주세요.")
    st.stop()


# ─────────────────────────────────────────────
# 🧹 PREPROCESSING 
# ─────────────────────────────────────────────
items_df = items_df.merge(
    meetings_df[["meeting_id", "meeting_date"]],
    on="meeting_id",
    how="left"
)

items_df["meeting_date"] = pd.to_datetime(items_df["meeting_date"], errors="coerce")
meetings_df["meeting_date"] = pd.to_datetime(meetings_df["meeting_date"], errors="coerce")

# 데이터 누락 방지를 위해 날짜 기준 정렬 및 주차 생성
meetings_df = meetings_df.sort_values("meeting_date")
items_df = items_df.sort_values("meeting_date")

meetings_df["week"] = meetings_df["meeting_date"].dt.to_period("W").astype(str)
items_df["week"] = items_df["meeting_date"].dt.to_period("W").astype(str)


# ─────────────────────────────────────────────
# 🎛 TOP FILTER BAR
# ─────────────────────────────────────────────
st.title("📊 Meeting Intelligence Dashboard")

colf1, colf2 = st.columns([2, 1])
with colf1:
    advertiser_list = ["전체"] + sorted(meetings_df["advertiser"].dropna().unique().tolist())
    selected_advertiser = st.selectbox("📌 광고주 필터", advertiser_list)
with colf2:
    threshold = st.slider("🔎 Review 필요 Confidence 기준", 0.0, 1.0, 0.7, 0.05)

# 필터링 적용
if selected_advertiser != "전체":
    filtered_items = items_df[items_df["advertiser"] == selected_advertiser]
    filtered_meetings = meetings_df[meetings_df["advertiser"] == selected_advertiser]
else:
    filtered_items = items_df
    filtered_meetings = meetings_df

pending_count = len(filtered_items[filtered_items["status"] == "pending"])


# ─────────────────────────────────────────────
# 📦 KPI CARDS
# ─────────────────────────────────────────────
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

# 1. 총 회의 수
kpi1.markdown(
    f'<div data-testid="metric-container">'
    f'<div style="color: #F1F5F9 !important; font-size: 14px; font-weight: 600; margin-bottom: 8px;">📅 총 회의 수</div>'
    f'<div style="color: #FFFFFF !important; font-size: 28px; font-weight: 700;">{len(filtered_meetings)}</div>'
    f'</div>', 
    unsafe_allow_html=True
)

# 2. 추출된 액션아이템
kpi2.markdown(
    f'<div data-testid="metric-container">'
    f'<div style="color: #F1F5F9 !important; font-size: 14px; font-weight: 600; margin-bottom: 8px;">📝 추출된 액션아이템</div>'
    f'<div style="color: #FFFFFF !important; font-size: 28px; font-weight: 700;">{len(filtered_items)}</div>'
    f'</div>', 
    unsafe_allow_html=True
)

# 3. 미완료(Pending)
kpi3.markdown(
    f'<div data-testid="metric-container">'
    f'<div style="color: #F1F5F9 !important; font-size: 14px; font-weight: 600; margin-bottom: 8px;">⛔ 미완료(Pending)</div>'
    f'<div style="color: #FFFFFF !important; font-size: 28px; font-weight: 700;">{pending_count}</div>'
    f'</div>', 
    unsafe_allow_html=True
)

# 4. 선택된 광고주
kpi4.markdown(
    f'<div data-testid="metric-container">'
    f'<div style="color: #F1F5F9 !important; font-size: 14px; font-weight: 600; margin-bottom: 8px;">👥 선택된 광고주</div>'
    f'<div style="color: #FFFFFF !important; font-size: 24px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{selected_advertiser}</div>'
    f'</div>', 
    unsafe_allow_html=True
)


st.markdown("<br>", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 📑 TABS (화면 구조화 및 시각화 고도화)
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📈 발생 추이", 
    "👤 담당자별 현황", 
    "🔑 핵심 키워드", 
    "🤖 추출 퀄리티 체크"
])

# Plotly 공통 레이아웃 스타일 정의 (Toss 다크 폰트 및 그리드 반영)
plotly_layout_defaults = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(family="Pretendard, -apple-system, sans-serif", color='#b0b8c1', size=12),
    margin=dict(l=40, r=40, t=40, b=40),
    xaxis=dict(gridcolor='#223147', zeroline=False, tickfont=dict(color='#8b95a1')),
    yaxis=dict(gridcolor='#223147', zeroline=False, tickfont=dict(color='#8b95a1')),
    legend=dict(font=dict(color='#e5e8eb'), bgcolor='rgba(0,0,0,0)')
)

# ─────────────────────────────────────────────
# WIDGET 1: 주차별 회의·액션아이템 발생 추이
# ─────────────────────────────────────────────
with tab1:
    st.subheader("주차별 회의 및 액션아이템 발생 추이")
    
    # 데이터 집계 (주차 누락 방지를 위해 아우터 조인 형태 보완)
    mtg_cnt = filtered_meetings.groupby("week").size().reset_index(name="회의 수")
    act_cnt = filtered_items.groupby("week").size().reset_index(name="액션아이템 수")
    trend_df = pd.merge(mtg_cnt, act_cnt, on="week", how="outer").fillna(0).sort_values("week")
    
    if not trend_df.empty:
        fig1 = go.Figure()
        # 회의 수: 차분한 Slate 그레이톤 곡선
        fig1.add_trace(go.Scatter(
            x=trend_df["week"], y=trend_df["회의 수"], 
            name="회의 수", mode='lines+markers', 
            line=dict(color='#8b95a1', width=2, shape='spline') # 부드러운 곡선 적용
        ))
        # 액션아이템 수: 토스 시그니처 블루 곡선 + 하단 은은한 글로우
        fig1.add_trace(go.Scatter(
            x=trend_df["week"], y=trend_df["액션아이템 수"], 
            name="액션아이템 수", mode='lines+markers', 
            line=dict(color='#0064ff', width=4, shape='spline'), # 토스 블루 곡선 적용
            fill='tozeroy', 
            fillcolor='rgba(0, 100, 255, 0.08)' # 면적 글로우 효과
        ))
        
        fig1.update_layout(**plotly_layout_defaults, hovermode="x unified")
        fig1.update_xaxes(type='category') # X축 정렬 꼬임 강제 방지
        st.plotly_chart(fig1, use_container_width=True)
    else:
        st.info("추이를 표시할 데이터가 없습니다.")


# ─────────────────────────────────────────────
# WIDGET 2: 담당자별 미완료 액션아이템 Top N
# ─────────────────────────────────────────────
with tab2:
    st.subheader("담당자별 미완료(Pending) 워크로드")
    pending_items = filtered_items[filtered_items["status"] == "pending"]
    
    if not pending_items.empty:
        top_n = st.slider("표시할 담당자 수 (Top N)", 3, 15, 5)
        
        assignee_cnt = (
            pending_items.groupby(["assignee", "assignee_role"])
            .size()
            .reset_index(name="미완료 건수")
            .sort_values("미완료 건수", ascending=True) 
        )
        assignee_cnt["display_name"] = assignee_cnt["assignee"] + " (" + assignee_cnt["assignee_role"] + ")"
        top_assignees = assignee_cnt.tail(top_n) 
        
        # 토스형 블루-퍼플 그라데이션 히트맵 스타일 바 스케일 적용
        fig2 = px.bar(
            top_assignees, 
            x="미완료 건수", 
            y="display_name", 
            orientation='h',
            color="미완료 건수",
            color_continuous_scale=["#0064ff", "#5b36ff"]
        )
        fig2.update_layout(**plotly_layout_defaults, coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)
        
        # 상세 드릴다운 영역
        st.markdown("---")
        selected = st.selectbox("🎯 특정 담당자의 상세 액션아이템 보기", ["선택 안 함"] + assignee_cnt["assignee"].unique().tolist())
        
        if selected != "선택 안 함":
            detail_df = pending_items[pending_items["assignee"] == selected][
                ["title", "description", "due_date", "priority", "confidence"]
            ]
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
    else:
        st.success("🎉 모든 액션 아이템이 완료되었거나 미완료된 항목이 없습니다!")


# ─────────────────────────────────────────────
# WIDGET 3: 캠페인 / 광고주별 반복 이슈 키워드
# ─────────────────────────────────────────────
with tab3:
    st.subheader("반복 검출 키워드 Top 15")
    
    STOPWORDS = {"있어요","해요","입니다","하고","에서","으로","것","수","할","한","및","그","이","저","회의","진행", "내용"}
    
    def extract_keywords(texts):
        c = Counter()
        for t in texts:
            if not isinstance(t, str): continue
            words = re.findall(r"[가-힣a-zA-Z]{2,}", t)
            for w in words:
                if w not in STOPWORDS:
                    c[w] += 1
        return dict(c.most_common(15))

    if not filtered_items.empty:
        texts = filtered_items["title"].tolist() + filtered_items["description"].tolist()
        kw = extract_keywords(texts)
        
        if kw:
            kw_df = pd.DataFrame(list(kw.items()), columns=["단어", "빈도수"]).sort_values("빈도수", ascending=True)
            
            # 은은한 토스 블루 모노톤 스케일 매핑
            fig3 = px.bar(kw_df, x="빈도수", y="단어", orientation='h', color="빈도수", color_continuous_scale="Blues")
            fig3.update_layout(**plotly_layout_defaults, coloraxis_showscale=False)
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("분석할 키워드가 부족합니다.")
    else:
        st.info("데이터가 없습니다.")


# ─────────────────────────────────────────────
# WIDGET 4: LLM 추출 confidence 분포 + 낮은 항목 드릴다운
# ─────────────────────────────────────────────
with tab4:
    st.subheader("🤖 LLM 추출 신뢰도(Confidence) 분석")
    
    colA, colB, colC = st.columns(3)
    high_c = len(filtered_items[filtered_items["confidence"] >= 0.8])
    mid_c = len(filtered_items[(filtered_items["confidence"] >= 0.5) & (filtered_items["confidence"] < 0.8)])
    low_c = len(filtered_items[filtered_items["confidence"] < 0.5])
    
    colA.markdown(
        f'<div data-testid="metric-container">'
        f'<div style="color: #F1F5F9 !important; font-size: 14px; font-weight: 600; margin-bottom: 8px;">🟢 High (≥ 0.8)</div>'
        f'<div style="color: #FFFFFF !important; font-size: 28px; font-weight: 700;">{high_c} 건</div>'
        f'</div>', 
        unsafe_allow_html=True
    )
    
    # colB: Mid
    colB.markdown(
        f'<div data-testid="metric-container">'
        f'<div style="color: #F1F5F9 !important; font-size: 14px; font-weight: 600; margin-bottom: 8px;">🟡 Mid (0.5 ~ 0.8)</div>'
        f'<div style="color: #FFFFFF !important; font-size: 28px; font-weight: 700;">{mid_c} 건</div>'
        f'</div>', 
        unsafe_allow_html=True
    )
    
    # colC: Low
    colC.markdown(
        f'<div data-testid="metric-container">'
        f'<div style="color: #F1F5F9 !important; font-size: 14px; font-weight: 600; margin-bottom: 8px;">🔴 Low (< 0.5)</div>'
        f'<div style="color: #FFFFFF !important; font-size: 28px; font-weight: 700;">{low_c} 건</div>'
        f'</div>', 
        unsafe_allow_html=True
    )
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown("#### Confidence 연속 분포도")
    hist_values = filtered_items["confidence"].dropna()
    
    if not hist_values.empty:
        # 광택감을 주는 시안/민트그린 톤 히스토그램 변환
        fig4 = px.histogram(
            filtered_items, 
            x="confidence", 
            nbins=20, 
            range_x=[0, 1],
            color_discrete_sequence=['#00d4b2']
        )
        fig4.update_layout(
            **plotly_layout_defaults,
            bargap=0.15,
            xaxis_title="Confidence Score",
            yaxis_title="빈도 수"
        )
        st.plotly_chart(fig4, use_container_width=True)
    
    # 드릴다운 테이블
    low_conf = filtered_items[filtered_items["confidence"] <= threshold]
    st.markdown("---")
    st.markdown(f"### ⚠️ 검토가 필요한 항목 (Confidence ≤ {threshold})")
    
    if not low_conf.empty:
        st.dataframe(
            low_conf[["title", "assignee", "confidence", "due_date"]].sort_values("confidence"),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success(f"기준점({threshold}) 이하로 신뢰도가 낮은 항목이 없습니다.")


# ─────────────────────────────────────────────
# 🔧 SYSTEM LOGS
# ─────────────────────────────────────────────
if not logs_df.empty:
    st.markdown("<br><br>", unsafe_allow_html=True)
    with st.expander("🛠️ 시스템 백엔드 LLM 로그 확인"):
        st.dataframe(logs_df, use_container_width=True)