import re
from pipeline.db import get_connection

# ── 광고·마케팅 약어 사전 ────────────────────────────────────
ABBR_DICT: dict[str, str] = {
    r"\bCPM\b": "CPM(노출당 비용)",
    r"\bCPC\b": "CPC(클릭당 비용)",
    r"\bCPA\b": "CPA(전환당 비용)",
    r"\bCTR\b": "CTR(클릭률)",
    r"\bROAS\b": "ROAS(광고수익률)",
    r"\bROI\b": "ROI(투자수익률)",
    r"\bA/B\b": "A/B 테스트",
    r"\bCTA\b": "CTA(행동유도버튼)",
    r"\bGDN\b": "GDN(구글디스플레이네트워크)",
    r"\bMETA\b": "메타(페이스북/인스타그램)",
    r"\bKV\b": "KV(키비주얼)",
    r"\bBI\b": "BI(브랜드아이덴티티)",
    r"\bDA\b": "DA(디스플레이광고)",
    r"\bSA\b": "SA(검색광고)",
    r"\bR&R\b": "역할분담(R&R)",
    r"\bKPI\b": "KPI(핵심성과지표)",
    r"\bMOM\b": "MoM(전월대비)",
    r"\bYOY\b": "YoY(전년대비)",
    r"\bCV\b": "CV(전환)",
    r"\bIMP\b": "IMP(노출수)",
    r"\bVTR\b": "VTR(영상조회율)",
}


TAKE_UTTERANCES_QUERY ="""
        SELECT segment_id, meeting_id, speaker, role, text
        FROM utterances_raw
        WHERE meeting_id = ?
        ORDER BY segment_id
    """

PUSH_PROCESSED_QUERY = """
        INSERT INTO utterances_processed
        (segment_id, meeting_id, speaker, role,
        original_text, normalized_text, chunk_index)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """

# ── 발화 잡음 패턴 ───────────────────────────────────────────
NOISE_PATTERNS = [
    r"(음+|어+|아+|에+)\s*,?\s*",          # 필러: 음, 어, 아
    r"(네네|네,|아네|어어)\s*",              # 호응 필러
    r"\.\.\.",                              # 말줄임표 (의미 없는 경우 제거)
    r"\s{2,}",                              # 연속 공백 → 단일
]

TOPIC_SHIFT_KEYWORDS = [
    "그리고", "다음으로", "두 번째", "세 번째", "또", "아 그리고",
    "그 다음", "넘어가서", "다음 안건", "마지막으로",
]

def apply_abbr(text: str) -> str:
    for pattern, replacement in ABBR_DICT.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def remove_noise(text: str) -> str:
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text)
    return text.strip()


def normalize_utterance(text: str) -> str:
    text = apply_abbr(text)
    text = remove_noise(text)
    return text


# ── 의미 단위 청킹 ───────────────────────────────────────────
def _is_topic_shift(text: str) -> bool:
    return any(kw in text for kw in TOPIC_SHIFT_KEYWORDS)


def chunk_segments(segments: list[dict]) -> list[dict]:
    """
    발화 목록을 의미 단위 청크로 묶는다.
    - 동일 화자 연속 발화는 같은 청크
    - 주제 전환 키워드 등장 시 새 청크
    """
    if not segments:
        return []

    chunked = []
    chunk_index = 0
    prev_speaker = None

    for seg in segments:
        text = seg["normalized_text"]
        speaker = seg["speaker"]

        if prev_speaker is not None and (speaker != prev_speaker or _is_topic_shift(text)):
            chunk_index += 1

        chunked.append({**seg, "chunk_index": chunk_index})
        prev_speaker = speaker

    return chunked


def transform(meeting_id: str):
    """raw utterances → processed utterances 변환 후 DB 저장 (멱등)"""
    conn = get_connection()

    rows = conn.execute(TAKE_UTTERANCES_QUERY, (meeting_id,)).fetchall()

    if not rows:
        print(f"[Transform] No raw segments for {meeting_id}")
        conn.close()
        return

    # 정규화
    processed = []
    for row in rows:
        normalized = normalize_utterance(row["text"])
        processed.append({
            "segment_id": row["segment_id"],
            "meeting_id": row["meeting_id"],
            "speaker": row["speaker"],
            "role": row["role"],
            "original_text": row["text"],
            "normalized_text": normalized,
        })

    # 청킹
    chunked = chunk_segments(processed)

    with conn:
        for item in chunked:
            conn.execute(PUSH_PROCESSED_QUERY, (
                item["segment_id"], item["meeting_id"],
                item["speaker"], item["role"],
                item["original_text"], item["normalized_text"],
                item["chunk_index"],
            ))

    conn.close()
    print(f"[Transform] Processed {len(chunked)} segments → {chunked[-1]['chunk_index']+1} chunks")
