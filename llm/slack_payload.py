import json
import os
from datetime import datetime
from pipeline.db import get_connection


PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
CONFIDENCE_EMOJI = {"high": "✅", "medium": "⚠️", "low": "💥"}

SELECT_MEETING_QUERY = """
        SELECT * FROM meetings WHERE meeting_id = ?
    """
SELECT_ACTION_ITEMS_QUERY = """
        SELECT * FROM action_items
        WHERE meeting_id = ?
        ORDER BY confidence DESC
    """

def generate_slack_payload(meeting_id: str) -> dict:
    """
    meeting_id → Slack Block Kit 페이로드 생성
    """
    conn = get_connection()

    meeting = conn.execute(SELECT_MEETING_QUERY, (meeting_id,)).fetchone()
    items = conn.execute(SELECT_ACTION_ITEMS_QUERY, (meeting_id,)).fetchall()

    conn.close()

    if not meeting:
        return {}

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"▶ {meeting['title']} — 액션아이템",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*광고주*\n{meeting['advertiser']}"},
                {"type": "mrkdwn", "text": f"*회의일*\n{meeting['meeting_date']}"},
            ]
        },
    ]

    if meeting["summary"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*회의 요약*\n{meeting['summary']}"}
        })

    blocks.append({"type": "divider"})

    for i, item in enumerate(items, 1):
        priority_icon = PRIORITY_EMOJI.get(item["priority"], "🟡")
        conf_icon = CONFIDENCE_EMOJI.get(item["confidence_level"], "⚠️")
        due = item["due_date"] or "미정"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{priority_icon} *{i}. {item['title']}*\n"
                    f"• 담당: {item['assignee']} ({item['assignee_role']})\n"
                    f"• 기한: {due}\n"
                    f"• 내용: {item['description']}\n"
                    f"• 신뢰도: {conf_icon} {item['confidence']:.0%}"
                )
            }
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
            }
        ]
    })

    return {
        "channel": "#meeting-action-items", #os.getenv("SLACK_CHANNEL")
        "username": "Meeting Bot", #os.getenv("SLACK_USERNAME")
        "blocks": blocks
    }


def save_slack_payload(meeting_id: str, output_path: str = None) -> str:
    """페이로드를 JSON 파일로 저장"""
    payload = generate_slack_payload(meeting_id)

    output_path = f"data/processed/slack_payload_{meeting_id}.json"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return output_path
