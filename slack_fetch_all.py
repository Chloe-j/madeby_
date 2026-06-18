"""
Slack 전체 채널 데이터 수집 스크립트
- 봇이 접근 가능한 모든 채널
- 채널별 전체 메시지 (페이지네이션)
- 모든 스레드 답글 포함
- 채널별 JSON 파일 저장 + 전체 요약 JSON 저장

사전 준비:
  pip install slack-sdk python-dotenv
  .env 파일에 SLACK_BOT_TOKEN=xoxb-... 설정

필요한 Bot Token Scopes:
  channels:read, channels:history
  groups:read, groups:history
  (비공개 채널 수집 시 봇이 해당 채널에 초대되어 있어야 합니다)
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
if not SLACK_BOT_TOKEN:
    raise EnvironmentError(
        ".env 파일에 SLACK_BOT_TOKEN이 없습니다.\n"
        "SLACK_BOT_TOKEN=xoxb-... 를 추가해주세요."
    )

client = WebClient(token=SLACK_BOT_TOKEN)

# ── 설정 ──────────────────────────────────────────────────────────────────────

# 특정 기간만 수집하려면 UNIX timestamp 입력 (None = 전체)
OLDEST = None   # 예: "1704067200"  (2024-01-01 00:00:00 UTC)
LATEST = None   # 예: "1735689599"  (2024-12-31 23:59:59 UTC)

# 결과 저장 폴더
OUTPUT_DIR = Path("slack_export")

# 공개 채널만 수집할지 여부 (False = 비공개 채널도 포함)
PUBLIC_ONLY = False

# 아카이브된 채널 포함 여부
INCLUDE_ARCHIVED = False

# 스레드 호출 사이 간격 (초) — Rate limit 방지
THREAD_SLEEP = 0.3

# ─────────────────────────────────────────────────────────────────────────────


def _retry_on_rate_limit(fn, *args, **kwargs):
    """Rate limit 발생 시 Retry-After 만큼 대기 후 재시도"""
    while True:
        try:
            return fn(*args, **kwargs)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                wait = int(e.response.headers.get("Retry-After", 1))
                print(f"    ⚠️  Rate limited — {wait}초 대기 중...")
                time.sleep(wait)
            else:
                raise


def list_all_channels() -> list[dict]:
    """봇이 접근 가능한 전체 채널 목록 반환"""
    channel_types = "public_channel" if PUBLIC_ONLY else "public_channel,private_channel"
    channels, cursor = [], None
    while True:
        resp = _retry_on_rate_limit(
            client.conversations_list,
            limit=200,
            exclude_archived=not INCLUDE_ARCHIVED,
            types=channel_types,
            cursor=cursor,
        )
        channels.extend(resp["channels"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels


def fetch_channel_info(channel_id: str) -> dict:
    return _retry_on_rate_limit(client.conversations_info, channel=channel_id)["channel"]


def fetch_channel_members(channel_id: str) -> list[str]:
    members, cursor = [], None
    while True:
        resp = _retry_on_rate_limit(
            client.conversations_members,
            channel=channel_id,
            limit=200,
            cursor=cursor,
        )
        members.extend(resp["members"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return members


def fetch_all_messages(channel_id: str) -> list[dict]:
    """채널 최상위 메시지 전체 수집"""
    messages, cursor = [], None
    while True:
        params = dict(channel=channel_id, limit=200, cursor=cursor)
        if OLDEST:
            params["oldest"] = OLDEST
        if LATEST:
            params["latest"] = LATEST
        resp = _retry_on_rate_limit(client.conversations_history, **params)
        messages.extend(resp["messages"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not resp.get("has_more"):
            break
    return messages


def fetch_thread_replies(channel_id: str, thread_ts: str) -> list[dict]:
    """스레드 답글 전체 수집 (원본 메시지 포함 반환)"""
    replies, cursor = [], None
    while True:
        resp = _retry_on_rate_limit(
            client.conversations_replies,
            channel=channel_id,
            ts=thread_ts,
            limit=200,
            cursor=cursor,
        )
        batch = resp["messages"] if not replies else resp["messages"][1:]
        replies.extend(batch)
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not resp.get("has_more"):
            break
    return replies


def fetch_one_channel(channel: dict, idx: int, total: int) -> dict:
    """채널 하나의 전체 데이터 수집"""
    cid = channel["id"]
    cname = channel.get("name", cid)
    print(f"\n[{idx}/{total}] #{cname}  ({cid})")

    try:
        info = fetch_channel_info(cid)
    except SlackApiError as e:
        print(f"  ⚠️  채널 정보 수집 실패: {e.response['error']} — 건너뜀")
        return None

    try:
        members = fetch_channel_members(cid)
        print(f"  멤버: {len(members)}명")
    except SlackApiError:
        members = []

    try:
        messages = fetch_all_messages(cid)
        print(f"  메시지: {len(messages)}개")
    except SlackApiError as e:
        print(f"  ⚠️  메시지 수집 실패: {e.response['error']} — 건너뜀")
        return None

    # 스레드 답글 수집
    threaded = [m for m in messages if int(m.get("reply_count", 0)) > 0]
    print(f"  스레드: {len(threaded)}개 처리 중...")
    total_replies = 0
    for msg in threaded:
        try:
            replies = fetch_thread_replies(cid, msg["ts"])
            msg["thread_replies"] = replies[1:]   # index 0 = 원본 메시지
            total_replies += len(msg["thread_replies"])
        except SlackApiError as e:
            msg["thread_replies"] = []
            print(f"    ⚠️  스레드 수집 실패 ts={msg['ts']}: {e.response['error']}")
        time.sleep(THREAD_SLEEP)

    print(f"  답글: {total_replies}개")

    return {
        "fetched_at": datetime.now().isoformat(),
        "channel_info": info,
        "members": members,
        "total_messages": len(messages),
        "total_thread_replies": total_replies,
        "messages": messages,
    }


def save_json(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size_kb = path.stat().st_size / 1024
    print(f"  저장: {path}  ({size_kb:.1f} KB)")


# ── 실행 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Slack 전체 채널 수집 시작")
    print(f"  저장 경로: {run_dir}")
    print("=" * 60)

    print("\n채널 목록 수집 중...")
    channels = list_all_channels()
    print(f"총 {len(channels)}개 채널 발견\n")

    summary = {
        "run_at": run_ts,
        "total_channels": len(channels),
        "channels": [],
    }

    for idx, ch in enumerate(channels, 1):
        data = fetch_one_channel(ch, idx, len(channels))
        if data is None:
            summary["channels"].append({
                "id": ch["id"],
                "name": ch.get("name", ""),
                "status": "failed",
            })
            continue

        cname = data["channel_info"].get("name", ch["id"])
        filename = run_dir / f"{cname}.json"
        save_json(data, filename)

        summary["channels"].append({
            "id": ch["id"],
            "name": cname,
            "status": "ok",
            "total_messages": data["total_messages"],
            "total_thread_replies": data["total_thread_replies"],
            "members": len(data["members"]),
            "file": str(filename),
        })

    # 전체 요약 저장
    summary_path = run_dir / "_summary.json"
    save_json(summary, summary_path)

    # 최종 결과 출력
    ok = [c for c in summary["channels"] if c["status"] == "ok"]
    fail = [c for c in summary["channels"] if c["status"] == "failed"]
    total_msg = sum(c.get("total_messages", 0) for c in ok)
    total_rep = sum(c.get("total_thread_replies", 0) for c in ok)

    print(f"\n{'=' * 60}")
    print("  수집 완료 요약")
    print(f"{'=' * 60}")
    print(f"  성공 채널    : {len(ok)}개")
    print(f"  실패 채널    : {len(fail)}개")
    print(f"  총 메시지    : {total_msg}개")
    print(f"  총 스레드 답글: {total_rep}개")
    print(f"  저장 경로    : {run_dir}/")
    print(f"  요약 파일    : {summary_path}")
