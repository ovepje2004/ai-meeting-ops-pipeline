#!/usr/bin/env python3
"""
전체 파이프라인 실행 엔트리포인트
Usage: python scripts/run_pipeline.py [--json data/raw/ko_meeting_3speakers.json]
"""
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from pipeline.db import init_db
from pipeline.ingest import ingest
from pipeline.transform import transform
from llm.extractor import extract
from llm.slack_payload import save_slack_payload


def run(json_path: str, advertiser: str = "노바드림", title: str = "캠페인 사전 정렬 회의"):
    print("\n" + "="*50)
    print("  Meeting Pipeline 시작")
    print("="*50)

    # Step 1: DB 초기화
    print("\n[Step 1] DB 초기화")
    init_db()

    # Step 2: Raw 데이터 적재
    print(f"\n[Step 2] Ingest: {json_path}")
    meeting_id = ingest(json_path, advertiser=advertiser, title=title)

    # Step 3: 전처리 (정규화 + 청킹)
    print(f"\n[Step 3] Transform: {meeting_id}")
    transform(meeting_id)

    # Step 4: LLM 액션아이템 추출
    print(f"\n[Step 4] LLM Extract: {meeting_id}")
    result = extract(meeting_id, advertiser=advertiser)

    if result:
        print(f"\n✅ 추출 완료: {len(result.action_items)}개 액션아이템")
        print(f"📝 요약: {result.meeting_summary[:80]}...")

        # Step 5: Slack 페이로드 생성
        print(f"\n[Step 5] Slack Payload 생성")
        slack_path = save_slack_payload(meeting_id)
        print(f"📤 Slack 페이로드: {slack_path}")
    else:
        print("\n⚠️  LLM 추출 실패 (재시도 초과)")

    print("\n" + "="*50)
    print(f"  Pipeline 완료  |  meeting_id: {meeting_id}")
    print("="*50 + "\n")
    return meeting_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meeting Pipeline Runner")
    parser.add_argument(
        "--json",
        default="data/raw/ko_meeting_3speakers.json",
        help="transcript JSON 경로"
    )
    parser.add_argument("--advertiser", default="노바드림")
    parser.add_argument("--title", default="캠페인 사전 정렬 회의")
    args = parser.parse_args()

    run(args.json, advertiser=args.advertiser, title=args.title)