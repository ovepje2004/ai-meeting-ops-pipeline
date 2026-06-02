import re
from pipeline.db import get_connection
from pipeline.models import ProcessedUtterance

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

# ── 발화 잡음 패턴 ───────────────────────────────────────────
NOISE_PATTERNS = [
    r"(음+|어+|아+|에+)\s*,?\s*",          # 필러: 음, 어, 아
    r"(네네|네,|아네|어어)\s*",              # 호응 필러
    r"\.\.\.",                              # 말줄임표 (의미 없는 경우 제거)
    r"\s{2,}",                              # 연속 공백 → 단일
]

# ── 암묵적 담당자 표현 정규화 ────────────────────────────────
IMPLICIT_ASSIGNEE_PATTERNS = [
    (r"제가\s*(챙길게요|할게요|맡을게요|보낼게요|확인할게요)", "담당자 자발적 수락"),
    (r"(저|제가)\s*(한번|좀)\s*(볼게요|확인해볼게요|체크할게요)", "담당자 자발적 수락"),
    (r"(팀장님|팀장)\s*(이|이서|이)\s*(결정|판단|확인)", "팀장 결정 필요"),
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
    text = remove_noise(text)
    text = apply_abbr(text)
    return text


# ── 의미 단위 청킹 ───────────────────────────────────────────
# 같은 화자가 연속으로 이어지거나, 주제 전환 키워드가 없으면 같은 청크로 묶음
TOPIC_SHIFT_KEYWORDS = [
    "그리고", "다음으로", "두 번째", "세 번째", "또", "아 그리고",
    "그 다음", "넘어가서", "다음 안건", "마지막으로",
]

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

    rows = conn.execute("""
        SELECT segment_id, meeting_id, speaker, role, text
        FROM utterances_raw
        WHERE meeting_id = ?
        ORDER BY segment_id
    """, (meeting_id,)).fetchall()

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
            conn.execute("""
                INSERT OR REPLACE INTO utterances_processed
                    (segment_id, meeting_id, speaker, role,
                     original_text, normalized_text, chunk_index)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                item["segment_id"], item["meeting_id"],
                item["speaker"], item["role"],
                item["original_text"], item["normalized_text"],
                item["chunk_index"],
            ))

    conn.close()
    print(f"[Transform] Processed {len(chunked)} segments → {chunked[-1]['chunk_index']+1} chunks")


if __name__ == "__main__":
    import sys
    meeting_id = sys.argv[1] if len(sys.argv) > 1 else None
    if meeting_id:
        transform(meeting_id)