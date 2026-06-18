"""
Slack 채널 데이터 전체 수집 스크립트
- 메시지 전체 (페이지네이션)
- 모든 스레드 답글 포함
- 결과를 JSON 파일로 저장

사전 준비:
  pip install slack-sdk python-dotenv
  .env 파일에 SLACK_BOT_TOKEN=xoxb-... 설정
"""

import os
import json
import time
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

if not SLACK_BOT_TOKEN:
    raise EnvironmentError(
        ".env 파일에 SLACK_BOT_TOKEN이 없습니다.\n"
        ".env 파일을 만들고 SLACK_BOT_TOKEN=xoxb-... 를 추가해주세요."
    )

client = WebClient(token=SLACK_BOT_TOKEN)


# ── 설정 ──────────────────────────────────────────────────────────────────────

TARGET_CHANNEL = "YOUR_CHANNEL_ID"   # 예: "C12345678"  ← 여기만 바꾸면 됩니다

# 특정 기간만 수집하려면 UNIX timestamp 입력 (None = 전체)
OLDEST = None   # 예: "1704067200"  (2024-01-01 00:00:00 UTC)
LATEST = None   # 예: "1735689599"  (2024-12-31 23:59:59 UTC)

# ─────────────────────────────────────────────────────────────────────────────


def _handle_rate_limit(e: SlackApiError) -> bool:
    """Rate limit 에러면 대기 후 True 반환, 그 외 에러면 재발생"""
    if e.response["error"] == "ratelimited":
        wait = int(e.response.headers.get("Retry-After", 1))
        print(f"    ⚠️  Rate limited — {wait}초 대기 중...")
        time.sleep(wait)
        return True
    raise


def list_channels() -> list[dict]:
    """봇이 접근 가능한 채널 목록 반환"""
    channels, cursor = [], None
    while True:
        try:
            resp = client.conversations_list(
                limit=200,
                exclude_archived=True,
                types="public_channel,private_channel",
                cursor=cursor,
            )
        except SlackApiError as e:
            if _handle_rate_limit(e):
                continue
        channels.extend(resp["channels"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels


def fetch_channel_info(channel_id: str) -> dict:
    return client.conversations_info(channel=channel_id)["channel"]


def fetch_channel_members(channel_id: str) -> list[str]:
    members, cursor = [], None
    while True:
        try:
            resp = client.conversations_members(channel=channel_id, limit=200, cursor=cursor)
        except SlackApiError as e:
            if _handle_rate_limit(e):
                continue
        members.extend(resp["members"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return members


def fetch_all_messages(channel_id: str) -> list[dict]:
    """채널 최상위 메시지 전체 수집 (스레드 원본 포함, 답글 제외)"""
    messages, cursor = [], None
    while True:
        params = dict(channel=channel_id, limit=200, cursor=cursor)
        if OLDEST:
            params["oldest"] = OLDEST
        if LATEST:
            params["latest"] = LATEST
        try:
            resp = client.conversations_history(**params)
        except SlackApiError as e:
            if _handle_rate_limit(e):
                continue
        messages.extend(resp["messages"])
        print(f"    메시지 {len(messages)}개 수집됨...")
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not resp.get("has_more"):
            break
    return messages


def fetch_thread_replies(channel_id: str, thread_ts: str) -> list[dict]:
    """
    스레드 답글 전체 수집.
    반환값: [원본메시지, 답글1, 답글2, ...]
    """
    replies, cursor = [], None
    while True:
        try:
            resp = client.conversations_replies(
                channel=channel_id, ts=thread_ts, limit=200, cursor=cursor
            )
        except SlackApiError as e:
            if _handle_rate_limit(e):
                continue

        # 첫 페이지는 원본 포함, 이후 페이지는 원본(index 0) 중복 제거
        batch = resp["messages"] if not replies else resp["messages"][1:]
        replies.extend(batch)

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not resp.get("has_more"):
            break
    return replies


def fetch_all_channel_data(channel_id: str) -> dict:
    """채널 전체 데이터 수집 (메시지 + 모든 스레드 답글)"""
    print(f"\n{'='*55}")
    print(f" 채널 데이터 수집 시작: {channel_id}")
    print(f"{'='*55}")

    print("\n[1/4] 채널 정보 수집 중...")
    info = fetch_channel_info(channel_id)
    print(f"  채널명: #{info.get('name', channel_id)}")

    print("\n[2/4] 멤버 목록 수집 중...")
    members = fetch_channel_members(channel_id)
    print(f"  멤버 수: {len(members)}명")

    print("\n[3/4] 메시지 수집 중...")
    messages = fetch_all_messages(channel_id)
    print(f"  총 메시지: {len(messages)}개")

    print("\n[4/4] 스레드 답글 수집 중...")
    threaded = [m for m in messages if int(m.get("reply_count", 0)) > 0]
    print(f"  스레드 있는 메시지: {len(threaded)}개")

    total_replies = 0
    for i, msg in enumerate(threaded, 1):
        reply_count = msg.get("reply_count", 0)
        print(f"  [{i}/{len(threaded)}] ts={msg['ts']}  예상 답글 {reply_count}개")
        replies = fetch_thread_replies(channel_id, msg["ts"])
        # replies[0]은 원본 메시지 — 답글만 별도 저장
        msg["thread_replies"] = replies[1:]
        total_replies += len(msg["thread_replies"])
        time.sleep(0.3)  # 연속 호출 간격

    print(f"\n  수집된 스레드 답글 합계: {total_replies}개")

    return {
        "fetched_at": datetime.now().isoformat(),
        "channel_info": info,
        "members": members,
        "total_messages": len(messages),
        "total_thread_replies": total_replies,
        "messages": messages,      # 각 메시지 안에 thread_replies 포함
    }


def save_json(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size_kb = os.path.getsize(path) / 1024
    print(f"\n저장 완료: {path}  ({size_kb:.1f} KB)")


# ── 실행 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ── 채널 목록 출력 (어떤 채널 ID를 써야 할지 모를 때 참고) ──
    print("접근 가능한 채널 목록:")
    for ch in list_channels():
        print(f"  #{ch['name']:<30} ID: {ch['id']}")

    # ── 채널 ID가 설정되지 않으면 여기서 중단 ──
    if TARGET_CHANNEL == "YOUR_CHANNEL_ID":
        print("\n▶ TARGET_CHANNEL 변수를 위 목록의 ID로 변경한 뒤 다시 실행하세요.")
    else:
        data = fetch_all_channel_data(TARGET_CHANNEL)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"slack_{data['channel_info']['name']}_{ts}.json"
        save_json(data, output)

        print(f"\n{'='*55}")
        print(" 수집 완료 요약")
        print(f"{'='*55}")
        print(f"  채널명       : #{data['channel_info']['name']}")
        print(f"  멤버 수      : {len(data['members'])}명")
        print(f"  총 메시지    : {data['total_messages']}개")
        print(f"  스레드 답글  : {data['total_thread_replies']}개")
        print(f"  저장 파일    : {output}")
