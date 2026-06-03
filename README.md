# ai-meeting-ops-pipeline

광고 에이전시 회의록을 자동으로 분석해 액션아이템을 추출하고 Slack으로 전달하는 AI 파이프라인입니다.

---

## 실행 방법

### 요구 환경

- 🐍 Python 3.11 이상 (3.13 최적)
- 🔑 Gemini API 키

### 설치

```bash
git clone https://github.com/ovepje2004/ai-meeting-ops-pipeline.git
cd ai-meeting-ops-pipeline
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 환경 변수 설정

📌.env는 반드시 프로젝트 루트에 위치

```bash
# .env 파일 생성
GEMINI_API_KEY=your_api_key_here
```

### 파이프라인 한 줄 실행

```bash
python scripts/run_pipeline.py \
  --json data/raw/ko_meeting_3speakers.json \
  --advertiser "광고주명" \
  --title "회의 제목"
```

실행 시 다음 순서로 처리됩니다.

1. DB 초기화 (`data/meeting_pipeline.db` 자동 생성)
2. JSON 파싱 및 DB 적재
3. 발화 정규화 및 청킹
4. Gemini API 호출 및 액션아이템 추출
5. Slack payload JSON 생성 (`data/processed/` 저장)

💾 파이프라인 로컬 실행 영상: [구글 드라이브 - 파이프라인 실행 영상(47초)](https://drive.google.com/file/d/1IOmHHnOVKv5xXPFJs_5vVgagJDf7qqy9/view?usp=sharing)

### 대시보드 한 줄 실행

data/meeting_pipeline.db에 적재된 내용이 없으면 시각화 되지 않음.

💾 (옵션) 파이프라인 실행 단계 스킵을 위한 db 제공: [구글 드라이브 - 이미 생성된 db파일](https://drive.google.com/file/d/1a8WR5V5SwGVL7ohpx_TOctbb4dCfHpF3/view?usp=sharing)

📌 위 db 파일은 반드시 data/meeting_pipeline.db에 위치.

```bash
streamlit run dashboards/app.py
```

💾 대시보드 로컬 실행 영상: [구글 드라이브 - 대시보드 실행 영상(1분 34초)](https://drive.google.com/file/d/17JcwpgADCx--dcfibBTAbk-NHFFVyTme/view?usp=sharing)

📊 실행결과 예시
<img width="1913" height="881" alt="image" src="https://github.com/user-attachments/assets/80aeedc2-88d7-4da4-8576-7727cea0b4b7" />


### 입력 데이터 형식

```json
{
  "language": "ko",
  "speaker_count": 3,
  "segment_count": 37,
  "speakers": [
    { "name": "이름", "role": "직위" }
  ],
  "segments": [
    { "id": 1, "line_no": 1, "speaker": "이름", "role": "직위", "text": "..." }
  ]
}
```

---

## 기술 스택 선택 근거

| 🧩 항목 | ⚙️ 기술 | 선택 이유 | ⚠️ trade-off |
| --- | --- | --- | --- |
| 회의 데이터 처리 | Python, Pydantic v2 | `model_validator` / `field_validator`로 LLM 응답 스키마 강제 및 필드 보정을 선언적으로 처리 | - |
| 데이터 저장 | SQLite | 단일 파일로 별도 서버 없이 즉시 실행 가능. WAL 모드로 읽기/쓰기 동시 접근 부분 허용 | 동시 쓰기 시 락 문제, 수백 건 이상에서 쿼리 성능 저하. 확장 시 PostgreSQL 전환 필요 |
| LLM API | Gemini 2.5 Flash (google-genai) | 속도·비용 효율성. 회의 1건당 추출 약 20초, Pro 대비 비용 낮음 | confidence를 0.05 단위로 뭉뚱그려 내는 경향. 정밀도 요구 시 Pro 또는 타 모델 교체 고려 |
| 대시보드 | Streamlit, Plotly, Pandas | 빠른 프로토타이핑. `@st.cache_data(ttl=30)`으로 30초 단위 갱신 | 실시간성 없음. 사용자 증가 시 세션마다 DB 커넥션을 새로 열어 부담 증가 |

## 아키텍처 및 데이터 흐름

<img width="813" height="531" alt="image" src="https://github.com/user-attachments/assets/cbc89fff-9489-4e8b-b491-c8f26d64eef5" />

```
회의 JSON
    │
    ▼
📄 [Ingest]  pipeline/ingest.py
  - JSON 파싱 (Pydantic RawTranscript)
  - meetings / speakers / utterances_raw → SQLite
  - INSERT OR IGNORE (멱등)
    │
    ▼
🔧 [Transform]  pipeline/transform.py
  - utterances_raw 조회
  - 약어 치환 (CPM, ROAS, CTA 등 20종)
  - 필러 제거 (음, 어, 아, 네네 등)
  - 화자 전환 / 주제 전환 키워드 기준 청킹
  - utterances_processed → SQLite
    │
    ▼
🤖 [LLM Extract]  llm/extractor.py
  - utterances_processed 조회
  - 프롬프트 생성 (build_extraction_prompt)
  - Gemini API 호출 (temperature=0.2, max_tokens=8192)
  - 최대 3회 재시도
  - llm_extraction_logs 기록
  - action_items → SQLite (DELETE → INSERT, 멱등)
    │
    ├──▶ 🧪 [Validator]  llm/validator.py
    │      - 마크다운 펜스 제거
    │      - JSON 파싱
    │      - Pydantic 검증 및 필드 보정
    │
    ▼
📤 [Slack Payload]  llm/slack_payload.py
  - action_items + meetings 조회
  - Slack Block Kit JSON 생성
  - data/processed/ 저장

📊 [Dashboard]  dashboards/app.py
  - SQLite 직접 조회
  - 추이 / 담당자 워크로드 / 키워드 / confidence 분포 시각화
```

### 모듈 분리 기준

`pipeline/`은 데이터 적재와 전처리, `llm/`은 LLM 호출과 결과 처리로 분리했습니다. Transform까지는 LLM 없이 독립 실행 가능하며, 프롬프트 변경이 파이프라인 로직에 영향을 주지 않도록 `llm/prompts.py`를 별도로 분리했습니다.

---

## 🧪 프롬프트 설계 근거

### 도메인 컨텍스트 주입

시스템 프롬프트에 "광고 에이전시 회의록 분석 전문가" 역할을 명시하고, CPM / ROAS / CTA / GDN 등 광고·마케팅 약어 20종을 Transform 단계에서 사전 치환합니다. LLM이 도메인 약어를 오해하는 경우를 줄이기 위한 전처리입니다.

### 액션아이템 판별 기준 명시

단순 의견, 문제 제기, 현황 공유는 액션아이템으로 추출하지 않도록 시스템 프롬프트에 명시했습니다. 명시적 업무 지시 / 자발적 의사 표현 / 합의·결정 표현 세 가지 유형을 판별 기준으로 제시합니다.

### Confidence 기준 명시

LLM이 자의적으로 confidence를 배분하지 않도록 4단계 기준을 프롬프트에 명시했습니다.

- ✅ 0.8 이상: 담당자·내용·기한이 명확히 언급됨
- ⚠️ 0.5~0.79: 담당자 또는 기한이 암묵적
- 💥 0.5 미만: 내용이 불분명하거나 결정이 흐릿함
- 💥 0.3 미만: 방향성만 존재

### Few-shot 예시

실제 광고 에이전시 발화 패턴으로 구성한 입출력 예시 1쌍을 프롬프트에 포함합니다. `source_utterances`에 segment_id를 기재하는 방식, `source_quote`에 원문을 그대로 인용하는 방식을 예시로 보여줍니다.

### 스키마 강제

프롬프트 말미에 출력 JSON 스키마를 명시하고 "반드시 JSON만 반환하세요"를 지시합니다. LLM이 마크다운 코드블록으로 감싸 반환하는 경우를 Validator의 `_strip_markdown_fences()`로 후처리합니다. 이는 LLM이 반환하는 JSON 데이터를 완전히 신뢰할 수 없다는 기본적인 가정을 전제로 합니다.

### 검증 및 재시도 전략

Pydantic 검증 실패 시 최대 3회(`MAX_RETRIES=3`) 재시도하며, 시도 간 2초 대기합니다. 모든 시도 결과는 `llm_extraction_logs`에 기록됩니다. 재시도 시 프롬프트를 변경하지 않으므로, 실패 원인이 모델 품질 문제인 경우 동일 결과가 반복될 수 있습니다.

---

## 가정 사항

**회의 날짜**
 
입력 JSON에 날짜 필드가 없어 `ingest.py`에서 `date.today()`로 파이프라인 실행 당일을 회의 날짜로 가정합니다.
 
**`--advertiser` / `--title` 필수 인자**
 
회의명과 광고주는 회의록 분석과 대시보드 필터링의 핵심 정보이나 입력 JSON에 포함되어 있지 않습니다. CLI 필수 인자로 받아 누락을 방지합니다.
 
**Slack 실제 전송 미구현**
 
Slack payload를 JSON 파일로 저장하는 것까지만 구현되어 있습니다. 실제 Webhook 전송 및 실패 시 재시도 로직은 구현되어 있지 않습니다.
 
**액션아이템 완료 처리 미구현**
 
후속 회의가 진행되어도 이전 회의의 액션아이템 상태가 자동으로 갱신되지 않아 모든 항목이 `pending`으로 유지됩니다. 해결 방안1. 후속 회의 발화를 LLM에 전달할 때 이전 액션아이템 목록도 함께 넘겨 완료 여부를 판별하는 방식 -> 회의가 쌓일수록 컨텍스트가 비대해져 비효율적
해결 방안2. Slack에서 완료 처리 시 Webhook으로 상태를 DB에 반영하는 방식 -> 향후 과제로 검토

**STT 미포함**
 
본 파이프라인은 이미 텍스트로 변환된 JSON을 입력으로 받습니다. 음성 파일에서 텍스트로 변환하는 STT 단계는 포함되어 있지 않으며, 외부 STT 도구 사용을 가정합니다.
 
