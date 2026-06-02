import json
import re
from pydantic import ValidationError
from pipeline.models import ActionItem, LLMExtractionResult


def _strip_markdown_fences(text: str) -> str:
    """LLM이 ```json ... ``` 로 감싸서 반환하는 경우 제거"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)

    # { ... } 블록만 추출
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1:
        text = text[start:end+1]

    return text.strip()


def _sanitize_action_item(raw: dict, meeting_id: str) -> dict:
    """필드 누락 시 기본값으로 보정"""
    raw.setdefault("meeting_id", meeting_id)
    raw.setdefault("description", raw.get("title", ""))
    raw.setdefault("assignee_role", "미확인")
    raw.setdefault("due_date", None)
    raw.setdefault("priority", "medium")
    raw.setdefault("source_utterances", [])
    raw.setdefault("source_quote", "")
    raw.setdefault("campaign", None)
    raw.setdefault("advertiser", "미확인")
    raw.setdefault("status", "pending")

    # confidence 범위 강제
    conf = raw.get("confidence", 0.5)
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.5
    raw["confidence"] = max(0.0, min(1.0, conf))

    return raw


def parse_and_validate(raw_text: str, meeting_id: str) -> LLMExtractionResult | None:
    """
    LLM raw 텍스트 → LLMExtractionResult
    실패 시 None 반환 (호출부에서 재시도 처리)
    """
    cleaned = _strip_markdown_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[Validator] JSON parse error: {e}")
        return None

    if "action_items" not in data:
        print("[Validator] 'action_items' 키 없음")
        return None

    valid_items: list[ActionItem] = []
    for i, raw_item in enumerate(data["action_items"]):
        sanitized = _sanitize_action_item(raw_item, meeting_id)
        try:
            item = ActionItem(**sanitized)
            valid_items.append(item)
        except ValidationError as e:
            print(f"[Validator] ActionItem #{i} 검증 실패, skip: {e.errors()[0]['msg']}")
            continue

    if not valid_items:
        print("[Validator] 유효한 액션아이템 없음")
        return None

    try:
        result = LLMExtractionResult(
            meeting_id=meeting_id,
            meeting_summary=data.get("meeting_summary", "요약 없음"),
            action_items=valid_items,
        )
        return result
    except ValidationError as e:
        print(f"[Validator] LLMExtractionResult 검증 실패: {e}")
        return None