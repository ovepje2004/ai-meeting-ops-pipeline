import json
import hashlib
from pathlib import Path
from datetime import date

from pipeline.db import get_connection
from pipeline.models import RawTranscript

INSERT_MEETING_SQL = """
INSERT OR IGNORE INTO meetings
    (meeting_id, title, advertiser, meeting_date, language, speaker_count, segment_count)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

INSERT_SPEAKER_SQL = """
INSERT OR IGNORE INTO speakers (meeting_id, name, role)
VALUES (?, ?, ?)
"""

INSERT_UTTERANCE_RAW_SQL = """
INSERT OR IGNORE INTO utterances_raw
    (segment_id, meeting_id, line_no, speaker, role, text)
VALUES (?, ?, ?, ?, ?, ?)
"""

def _make_meeting_id(file_path: Path) -> str:
    raw = file_path.stem 
    return "mtg_" + hashlib.md5(raw.encode()).hexdigest()[:10]


def ingest(json_path: str | Path, advertiser: str, title: str) -> str:
    """
    transcript JSON → DB 적재 (멱등: 이미 존재하면 skip)
    Returns: meeting_id
    """
    json_path = Path(json_path)
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    transcript = RawTranscript(**raw)

    meeting_id = _make_meeting_id(json_path)
    #meeting_date = date.today().isoformat()
    meeting_date = "2026-06-11"

    conn = get_connection()
    with conn:
        # ── meetings ─────────────────────────────────────────
        conn.execute(INSERT_MEETING_SQL, (meeting_id, title, advertiser, meeting_date,
                                          transcript.language, transcript.speaker_count, transcript.segment_count))

        # ── speakers ─────────────────────────────────────────
        for sp in transcript.speakers:
            conn.execute(INSERT_SPEAKER_SQL, (meeting_id, sp.name, sp.role))

        # ── utterances_raw ────────────────────────────────────
        for seg in transcript.segments:
            conn.execute(INSERT_UTTERANCE_RAW_SQL, (seg.id, meeting_id, seg.line_no, seg.speaker, seg.role, seg.text))

    conn.close()
    print(f"[Ingest] meeting_id={meeting_id}  segments={transcript.segment_count}")
    return meeting_id
