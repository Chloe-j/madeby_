"""
Slack 채널 데이터 전체 수집 스크립트
필요한 패키지: pip install slack-sdk python-dotenv
"""

import os
import json
import time
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

load_dotenv()

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=SLACK_TOKEN)


def fetch_all_messages(channel_id: str, oldest: str = None, latest: str = None) -> list[dict]:
    """채널의 모든 메시지를 페이지네이션으로 수집"""
    messages = []
    cursor = None

    while True:
        params = {
            "channel": channel_id,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest

        try:
            response = client.conversations_history(**params)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 1))
                print(f"Rate limited. {retry_after}초 후 재시도...")
                time.sleep(retry_after)
                continue
            raise

        messages.extend(response["messages"])
        print(f"  메시지 수집 중: {len(messages)}개")

        if not response.get("has_more"):
            break
        cursor = response["response_metadata"]["next_cursor"]

    return messages


def fetch_thread_replies(channel_id: str, thread_ts: str) -> list[dict]:
    """스레드 답글 전체 수집"""
    replies = []
    cursor = None

    while True:
        params = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor

        try:
            response = client.conversations_replies(**params)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 1))
                time.sleep(retry_after)
                continue
            raise

        # 첫 번째 항목은 원본 메시지이므로 첫 호출 시에만 포함
        batch = response["messages"] if not replies else response["messages"][1:]
        replies.extend(batch)

        if not response.get("has_more"):
            break
        cursor = response["response_metadata"]["next_cursor"]

    return replies


def fetch_channel_members(channel_id: str) -> list[str]:
    """채널 멤버 목록 수집"""
    members = []
    cursor = None

    while True:
        params = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor

        try:
            response = client.conversations_members(**params)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                time.sleep(int(e.response.headers.get("Retry-After", 1)))
                continue
            raise

        members.extend(response["members"])

        if not response.get("has_more"):
            break
        cursor = response["response_metadata"]["next_cursor"]

    return members


def fetch_channel_info(channel_id: str) -> dict:
    """채널 기본 정보 수집"""
    response = client.conversations_info(channel=channel_id)
    return response["channel"]


def fetch_all_channel_data(channel_id: str, include_threads: bool = True) -> dict:
    """채널의 모든 데이터를 수집하여 딕셔너리로 반환"""
    print(f"\n채널 {channel_id} 데이터 수집 시작...")

    # 채널 정보
    print("채널 정보 수집 중...")
    channel_info = fetch_channel_info(channel_id)
    channel_name = channel_info.get("name", channel_id)
    print(f"  채널명: #{channel_name}")

    # 멤버 목록
    print("멤버 목록 수집 중...")
    members = fetch_channel_members(channel_id)
    print(f"  멤버 수: {len(members)}명")

    # 메시지 전체
    print("메시지 수집 중...")
    messages = fetch_all_messages(channel_id)
    print(f"  총 메시지: {len(messages)}개")

    # 스레드 답글
    if include_threads:
        print("스레드 답글 수집 중...")
        threaded_messages = [m for m in messages if m.get("reply_count", 0) > 0]
        print(f"  스레드 있는 메시지: {len(threaded_messages)}개")

        for msg in threaded_messages:
            ts = msg["ts"]
            replies = fetch_thread_replies(channel_id, ts)
            msg["thread_replies"] = replies
            time.sleep(0.5)  # API rate limit 방지

    return {
        "channel_info": channel_info,
        "members": members,
        "messages": messages,
        "fetched_at": datetime.now().isoformat(),
        "total_messages": len(messages),
    }


def save_to_json(data: dict, output_path: str):
    """결과를 JSON 파일로 저장"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {output_path}")


def list_channels() -> list[dict]:
    """접근 가능한 모든 채널 목록 반환"""
    channels = []
    cursor = None

    while True:
        params = {"limit": 200, "exclude_archived": True, "types": "public_channel,private_channel"}
        if cursor:
            params["cursor"] = cursor

        try:
            response = client.conversations_list(**params)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                time.sleep(int(e.response.headers.get("Retry-After", 1)))
                continue
            raise

        channels.extend(response["channels"])

        if not response.get("has_more"):
            break
        cursor = response["response_metadata"]["next_cursor"]

    return channels


if __name__ == "__main__":
    # 사용 예시

    # 1. 채널 목록 확인
    print("접근 가능한 채널 목록:")
    channels = list_channels()
    for ch in channels:
        print(f"  - #{ch['name']}  (ID: {ch['id']})")

    # 2. 특정 채널 데이터 수집 (채널 ID 또는 이름으로 지정)
    TARGET_CHANNEL = "YOUR_CHANNEL_ID"  # 예: "C12345678" 또는 채널 목록에서 확인한 ID

    if TARGET_CHANNEL != "YOUR_CHANNEL_ID":
        data = fetch_all_channel_data(TARGET_CHANNEL, include_threads=True)

        # JSON 파일로 저장
        output_file = f"slack_{data['channel_info']['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_to_json(data, output_file)

        print(f"\n수집 완료:")
        print(f"  채널명: #{data['channel_info']['name']}")
        print(f"  멤버 수: {len(data['members'])}명")
        print(f"  총 메시지: {data['total_messages']}개")
    else:
        print("\nTARGET_CHANNEL을 실제 채널 ID로 변경해주세요.")
