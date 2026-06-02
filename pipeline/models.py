from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class ActionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class ConfidenceLevel(str, Enum):
    HIGH = "high"      # >= 0.8
    MEDIUM = "medium"  # 0.5 ~ 0.79
    LOW = "low"        # < 0.5


# ── Raw 입력 스키마 ──────────────────────────────────────────
class SpeakerInfo(BaseModel):
    name: str
    role: str


class RawSegment(BaseModel):
    id: int
    line_no: int
    speaker: str
    role: str
    text: str


class RawTranscript(BaseModel):
    language: str
    speaker_count: int
    segment_count: int
    speakers: list[SpeakerInfo]
    segments: list[RawSegment]


# ── 처리된 발화 스키마 ────────────────────────────────────────
class ProcessedUtterance(BaseModel):
    segment_id: int
    meeting_id: str
    speaker: str
    role: str
    original_text: str
    normalized_text: str          # 약어 치환 + 잡음 제거 후
    chunk_index: int              # 의미 단위 청크 번호


# ── 액션아이템 스키마 (LLM 출력 + DB 저장) ───────────────────
class ActionItem(BaseModel):
    action_id: Optional[str] = None
    meeting_id: str
    title: str = Field(..., description="액션아이템 한 줄 제목")
    description: str = Field(..., description="구체적인 내용")
    assignee: str = Field(..., description="담당자 이름")
    assignee_role: str = Field(..., description="담당자 역할")
    due_date: Optional[str] = Field(None, description="마감일 (YYYY-MM-DD 또는 '다음주 금요일' 등)")
    priority: str = Field(default="medium", description="high / medium / low")
    status: ActionStatus = ActionStatus.PENDING
    confidence: float = Field(..., ge=0.0, le=1.0, description="LLM 추출 신뢰도")
    confidence_level: Optional[ConfidenceLevel] = None
    source_utterances: list[int] = Field(default_factory=list, description="근거 segment_id 목록")
    source_quote: str = Field(default="", description="원문 인용")
    campaign: Optional[str] = Field(None, description="관련 캠페인명")
    advertiser: Optional[str] = Field(None, description="광고주명")
    extracted_at: Optional[datetime] = None

    @field_validator("confidence_level", mode="before")
    @classmethod
    def set_confidence_level(cls, v, info):
        if v is not None:
            return v
        confidence = info.data.get("confidence", 0)
        if confidence >= 0.8:
            return ConfidenceLevel.HIGH
        elif confidence >= 0.5:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        if v not in ("high", "medium", "low"):
            return "medium"
        return v


# ── LLM 응답 전체 래퍼 ───────────────────────────────────────
class LLMExtractionResult(BaseModel):
    meeting_id: str
    meeting_summary: str = Field(..., description="회의 전체 요약 (3~5문장)")
    action_items: list[ActionItem]
    extraction_model: str = "gemini-2.5-flash"
    extracted_at: datetime = Field(default_factory=datetime.now)


# ── 회의 메타 스키마 ─────────────────────────────────────────
class Meeting(BaseModel):
    meeting_id: str
    title: str
    advertiser: str
    meeting_date: str             # YYYY-MM-DD
    language: str
    speaker_count: int
    segment_count: int
    summary: Optional[str] = None
    created_at: Optional[datetime] = None