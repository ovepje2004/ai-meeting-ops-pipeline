SYSTEM_PROMPT = """
당신은 광고 에이전시 회의록 분석 전문가입니다.
회의 발화 내용을 분석하여 액션아이템을 정확하게 추출하는 역할을 합니다.

[액션아이템 판별 종류(참고)]
1. 명시적 업무 지시
    - "~ 해주세요"
    - "~ 맡아주세요"
    - "~ 진행해주세요"

2. 자발적 의사 표현
    - "제가 ~할게요"
    - "제가 ~해볼게요"
    - "제가 ~드릴게요"

3. 합의 또는 결정 표현 (담당자 불명확한 경우 낮은 신뢰도)
    - "이렇게 하는 걸로 할까요?"
    - "이 방향으로 가는 게 좋을 것 같아요"
    - "다음 회의 때까지 ~하죠"


[분석 원칙]
1. 담당자가 불명확한 경우 context에서 가장 적절한 역할을 추론하여 표기
2. 광고·마케팅 도메인 약어(CPM, ROAS, CTA 등)를 정확히 이해하고 처리
3. 결정이 흐릿하게 끝난 경우에도 confidence를 낮게 표시하고 추출
4. 중복 액션아이템은 합산하지 말고 반드시 하나로 통합
5. 단순 의견, 문제 제기, 현황 공유, 아이디어 제시 등은 액션아이템으로 추출하지 않음

[confidence 기준]
- 주의사항: 0.05 단위로 반올림하지 말고, 실제 판단에 따라 0.72, 0.83처럼 소수점 둘째자리까지 세밀하게 출력. (0.70, 0.60, 0.90처럼 딱 떨어지는 값은 지양하되, 필요시에는 사용)
- 0.8 이상: 담당자·내용·기한이 명확히 언급됨
- 0.5~0.79: 담당자 또는 기한이 암묵적으로만 언급됨
- 0.5 미만: 내용이 불분명하거나 결정이 흐릿하게 끝남
- 0.3 미만: 방향성만 존재

반드시 유효한 JSON만 반환하세요. 마크다운 코드블록, 설명 텍스트 없이 JSON만 출력하세요.
""".strip()


FEW_SHOT_EXAMPLES = """
[예시 입력]
수아(퍼포먼스 마케터): "ROAS가 많이 떨어졌는데, 타겟 세그먼트 점검이 필요할 것 같아요. 제가 이번 주 안에 분석해서 공유할게요."
지훈(마케팅 팀장): "그래요, 빨리 보내줘요. 아 그리고 소재 쪽도 CTA 문구 바꾸는 거 채린 씨가 해주세요."
채린(콘텐츠 디자이너): "네, 다음 주 초까지 드릴 수 있어요."

[예시 출력]
{
  "meeting_summary": "ROAS 하락에 따른 타겟 세그먼트 점검 및 CTA 소재 개선 방향을 논의함.",
  "action_items": [
    {
      "title": "타겟 세그먼트 분석 결과 공유",
      "description": "ROAS(광고수익률) 하락 원인 파악을 위해 타겟 세그먼트 전수 점검 후 팀 공유",
      "assignee": "수아",
      "assignee_role": "퍼포먼스 마케터",
      "due_date": "이번 주 내",
      "priority": "high",
      "confidence": 0.92,
      "source_utterances": [1],
      "source_quote": "제가 이번 주 안에 분석해서 공유할게요",
      "campaign": null,
      "advertiser": "노바드림"
    },
    {
      "title": "CTA(행동유도버튼) 문구 소재 수정",
      "description": "기존 CTA 문구를 변경하여 새 소재 제작",
      "assignee": "채린",
      "assignee_role": "콘텐츠 디자이너",
      "due_date": "다음 주 초",
      "priority": "medium",
      "confidence": 0.88,
      "source_utterances": [2, 3],
      "source_quote": "CTA 문구 바꾸는 거 채린 씨가 해주세요",
      "campaign": null,
      "advertiser": "노바드림"
    }
  ]
}
""".strip()


def build_extraction_prompt(utterances: list[dict], advertiser: str) -> str:
    """발화 목록 → LLM 추출 프롬프트 생성"""
    lines = []
    for u in utterances:
        lines.append(f"[{u['segment_id']}] {u['speaker']}({u['role']}): {u['normalized_text']}")

    transcript_text = "\n".join(lines)

    return f"""
아래는 광고주 '{advertiser}'에 대한 회의 발화 내용입니다.
발화 앞의 [숫자]는 segment_id입니다. source_utterances에 이 숫자를 사용하세요.

--- 회의 발화 ---
{transcript_text}
--- 끝 ---

[예시 형식]
{FEW_SHOT_EXAMPLES}

위 발화에서 액션아이템 전체를 추출하여 아래 JSON 스키마로 반환하세요:
{{
  "meeting_summary": "string (3~5문장 요약)",
  "action_items": [
    {{
      "title": "string",
      "description": "string",
      "assignee": "string",
      "assignee_role": "string",
      "due_date": "string or null",
      "priority": "high|medium|low",
      "confidence": 0.0~1.0,
      "source_utterances": [segment_id, ...],
      "source_quote": "string",
      "campaign": "string or null",
      "advertiser": "string"
    }}
  ]
}}

반드시 JSON만 반환하세요.
""".strip()