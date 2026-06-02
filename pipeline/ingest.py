import json
import hashlib
from pathlib import Path
from datetime import date

from pipeline.db import get_connection, init_db
from pipeline.models import RawTranscript


def _make_meeting_id(file_path: Path) -> str:
    """파일명 + 날짜 기반 결정적 ID 생성 → 멱등성 보장"""
    stem = file_path.stem  # ko_meeting_3speakers
    today = date.today().isoformat().replace("-", "")
    raw = f"{stem}_{today}"
    return "mtg_" + hashlib.md5(raw.encode()).hexdigest()[:10]


def ingest(json_path: str | Path, advertiser: str = "노바드림", title: str = "캠페인 사전 정렬 회의") -> str:
    """
    transcript JSON → DB 적재 (멱등: 이미 존재하면 skip)
    Returns: meeting_id
    """
    json_path = Path(json_path)
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    transcript = RawTranscript(**raw)

    meeting_id = _make_meeting_id(json_path)
    meeting_date = date.today().isoformat()

    conn = get_connection()
    with conn:
        # ── meetings ─────────────────────────────────────────
        conn.execute("""
            INSERT OR IGNORE INTO meetings
                (meeting_id, title, advertiser, meeting_date, language, speaker_count, segment_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (meeting_id, title, advertiser, meeting_date,
              transcript.language, transcript.speaker_count, transcript.segment_count))

        # ── speakers ─────────────────────────────────────────
        for sp in transcript.speakers:
            conn.execute("""
                INSERT OR IGNORE INTO speakers (meeting_id, name, role)
                VALUES (?, ?, ?)
            """, (meeting_id, sp.name, sp.role))

        # ── utterances_raw ────────────────────────────────────
        for seg in transcript.segments:
            conn.execute("""
                INSERT OR IGNORE INTO utterances_raw
                    (segment_id, meeting_id, line_no, speaker, role, text)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (seg.id, meeting_id, seg.line_no, seg.speaker, seg.role, seg.text))

    conn.close()
    print(f"[Ingest] meeting_id={meeting_id}  segments={transcript.segment_count}")
    return meeting_id


if __name__ == "__main__":
    init_db()
    mid = ingest("data/raw/ko_meeting_3speakers.json")
    print(f"Done: {mid}")