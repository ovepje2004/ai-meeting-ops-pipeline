import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "meeting_pipeline.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    with conn:
        conn.executescript("""
        -- 회의 메타 테이블
        CREATE TABLE IF NOT EXISTS meetings (
            meeting_id    TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            advertiser    TEXT NOT NULL,
            meeting_date  TEXT NOT NULL,
            language      TEXT DEFAULT 'ko',
            speaker_count INTEGER,
            segment_count INTEGER,
            summary       TEXT,
            created_at    TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 화자 테이블
        CREATE TABLE IF NOT EXISTS speakers (
            speaker_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id  TEXT NOT NULL REFERENCES meetings(meeting_id),
            name        TEXT NOT NULL,
            role        TEXT NOT NULL,
            UNIQUE(meeting_id, name)
        );

        -- 원천 발화 테이블 (raw)
        CREATE TABLE IF NOT EXISTS utterances_raw (
            segment_id    INTEGER,
            meeting_id    TEXT NOT NULL REFERENCES meetings(meeting_id),
            line_no       INTEGER,
            speaker       TEXT NOT NULL,
            role          TEXT NOT NULL,
            text          TEXT NOT NULL,
            PRIMARY KEY (meeting_id, segment_id)
        );

        -- 처리된 발화 테이블 (정규화 + 약어 치환)
        CREATE TABLE IF NOT EXISTS utterances_processed (
            segment_id      INTEGER,
            meeting_id      TEXT NOT NULL REFERENCES meetings(meeting_id),
            speaker         TEXT NOT NULL,
            role            TEXT NOT NULL,
            original_text   TEXT NOT NULL,
            normalized_text TEXT NOT NULL,
            chunk_index     INTEGER DEFAULT 0,
            PRIMARY KEY (meeting_id, segment_id)
        );

        -- 액션아이템 테이블
        CREATE TABLE IF NOT EXISTS action_items (
            action_id        TEXT PRIMARY KEY,
            meeting_id       TEXT NOT NULL REFERENCES meetings(meeting_id),
            title            TEXT NOT NULL,
            description      TEXT,
            assignee         TEXT NOT NULL,
            assignee_role    TEXT,
            due_date         TEXT,
            priority         TEXT DEFAULT 'medium',
            status           TEXT DEFAULT 'pending',
            confidence       REAL NOT NULL,
            confidence_level TEXT,
            source_utterances TEXT,   -- JSON array string
            source_quote     TEXT,
            campaign         TEXT,
            advertiser       TEXT,
            extracted_at     TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- LLM 추출 로그 (재시도 이력 포함)
        CREATE TABLE IF NOT EXISTS llm_extraction_logs (
            log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id    TEXT NOT NULL,
            attempt       INTEGER DEFAULT 1,
            model         TEXT,
            success       INTEGER DEFAULT 0,   -- 0/1
            error_message TEXT,
            raw_response  TEXT,
            created_at    TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """)
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")
