import os
import uuid
import json
import time
from datetime import datetime
from google import genai
from google.genai import types

from pipeline.db import get_connection
from pipeline.models import LLMExtractionResult, ActionItem
from llm.prompts import SYSTEM_PROMPT, build_extraction_prompt
from llm.validator import parse_and_validate

MODEL = "gemini-2.5-flash"
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
    return genai.Client(api_key=api_key)


def _fetch_utterances(meeting_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT segment_id, speaker, role, normalized_text
        FROM utterances_processed
        WHERE meeting_id = ?
        ORDER BY segment_id
    """, (meeting_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _call_gemini(client: genai.Client, prompt: str) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=8192,
        ),
    )
    text = response.text
    print(f"[Extractor] Raw response ({len(text)} chars):\n{text[:300]}...")
    return text


def _log_attempt(meeting_id: str, attempt: int, success: bool,
                 raw_response: str = "", error_message: str = ""):
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO llm_extraction_logs
                (meeting_id, attempt, model, success, error_message, raw_response)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (meeting_id, attempt, MODEL, int(success), error_message, raw_response))
    conn.close()


def _save_result(result: LLMExtractionResult):
    conn = get_connection()
    with conn:
        # 회의 요약 업데이트
        conn.execute("""
            UPDATE meetings SET summary = ? WHERE meeting_id = ?
        """, (result.meeting_summary, result.meeting_id))

        # 기존 액션아이템 삭제 후 재적재 (멱등)
        conn.execute("DELETE FROM action_items WHERE meeting_id = ?", (result.meeting_id,))

        for item in result.action_items:
            action_id = f"act_{uuid.uuid4().hex[:10]}"
            conn.execute("""
                INSERT INTO action_items (
                    action_id, meeting_id, title, description,
                    assignee, assignee_role, due_date, priority, status,
                    confidence, confidence_level, source_utterances, source_quote,
                    campaign, advertiser, extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action_id, item.meeting_id, item.title, item.description,
                item.assignee, item.assignee_role, item.due_date,
                item.priority, item.status.value,
                item.confidence, item.confidence_level.value if item.confidence_level else None,
                json.dumps(item.source_utterances, ensure_ascii=False),
                item.source_quote, item.campaign, item.advertiser,
                result.extracted_at.isoformat(),
            ))
    conn.close()
    print(f"[Extractor] Saved {len(result.action_items)} action items for {result.meeting_id}")


def extract(meeting_id: str, advertiser: str = "노바드림") -> LLMExtractionResult | None:
    """
    메인 추출 함수: 발화 로딩 → 프롬프트 생성 → Gemini 호출 → 검증 → DB 저장
    재시도 MAX_RETRIES회 (스키마 검증 실패 시)
    """
    utterances = _fetch_utterances(meeting_id)
    if not utterances:
        print(f"[Extractor] No processed utterances for {meeting_id}")
        return None

    client = _get_client()
    prompt = build_extraction_prompt(utterances, advertiser)

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[Extractor] Attempt {attempt}/{MAX_RETRIES} for {meeting_id}")
        try:
            raw_response = _call_gemini(client, prompt)
            result = parse_and_validate(raw_response, meeting_id)

            if result:
                _log_attempt(meeting_id, attempt, success=True, raw_response=raw_response)
                _save_result(result)
                return result
            else:
                _log_attempt(meeting_id, attempt, success=False,
                             raw_response=raw_response, error_message="validation_failed")
                if attempt < MAX_RETRIES:
                    print(f"[Extractor] 검증 실패, {RETRY_DELAY}초 후 재시도...")
                    time.sleep(RETRY_DELAY)

        except Exception as e:
            error_msg = str(e)
            print(f"[Extractor] API 오류: {error_msg}")
            _log_attempt(meeting_id, attempt, success=False, error_message=error_msg)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    print(f"[Extractor] {MAX_RETRIES}회 시도 후 실패: {meeting_id}")
    return None


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    if mid:
        result = extract(mid)
        if result:
            print(f"\n요약: {result.meeting_summary}")
            for item in result.action_items:
                print(f"  - [{item.confidence:.2f}] {item.title} → {item.assignee}")