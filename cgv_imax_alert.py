# -*- coding: utf-8 -*-
"""
CGV 용산/왕십리/천호 '오디세이' IMAX 예매 오픈 알림 (신규 CGV API 기준, 2026-08)
- cgv.co.kr 리뉴얼로 옛 iframeTheater.aspx URL이 죽어서 새 JSON API로 교체
- 새 API: /api/v1/booking/searchMovScnInfo (평문 GET, 암호화 없음)
- 새로운 날짜에 오디세이 IMAX 회차가 뜨면 ntfy/텔레그램 알림

로컬 실행:      python cgv_imax_alert.py
GitHub Actions: python cgv_imax_alert.py --once

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, NTFY_TOPIC
"""

import json
import os
import sys
import time
from datetime import date, timedelta

import requests

MOVIE_KEYWORD = "오디세이"        # 빈 문자열("")이면 모든 IMAX 상영 감지
IMAX_KEYWORDS = ("IMAX", "아이맥스")  # scnsNm/expoScnsNm에 이 중 하나라도 포함되면 IMAX관으로 판단
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "여기에-토픽이름")

THEATERS = {"용산아이파크몰": "0013", "왕십리": "0074", "천호": "0199"}
CO_CD = "A420"  # CGV 법인코드 (고정값)
DAYS_AHEAD = 21
INTERVAL_SEC = 300
STATE_FILE = "imax_state.json"

API_URL = "https://cgv.co.kr/api/v1/booking/searchMovScnInfo"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://cgv.co.kr/",
    "Accept": "application/json",
}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {name: [] for name in THEATERS}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def movie_imax_open(theater_code: str, ymd: str) -> bool:
    """해당 극장·날짜에 (키워드 영화의) IMAX 회차가 있는지"""
    params = {
        "coCd": CO_CD,
        "siteNo": theater_code,
        "scnYmd": ymd,
        "rtctlScopCd": "08",
    }
    try:
        r = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        body = r.json()
    except requests.RequestException as e:
        print(f"  [요청 실패] {ymd}: {e}")
        return False
    except ValueError as e:
        print(f"  [JSON 파싱 실패] {ymd}: {e}")
        return False

    if body.get("statusCode") != 0:
        print(f"  [API 오류] {ymd}: {body.get('statusMessage')}")
        return False

    for item in body.get("data") or []:
        movie_name = (item.get("movNm") or "") + (item.get("expoProdNm") or "")
        screen_name = (item.get("scnsNm") or "") + (item.get("expoScnsNm") or "")
        is_target_movie = (not MOVIE_KEYWORD) or (MOVIE_KEYWORD in movie_name)
        is_imax = any(kw in screen_name for kw in IMAX_KEYWORDS)
        if is_target_movie and is_imax:
            return True
    return False


def notify(title: str, message: str):
    print(f"\n🔔 {title}\n{message}\n")
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=10)
    except Exception:
        pass

    if NTFY_TOPIC and "토픽이름" not in NTFY_TOPIC:
        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=message.encode("utf-8"),
                headers={"Title": title.encode("utf-8"), "Priority": "high", "Tags": "clapper"},
                timeout=10,
            )
        except requests.RequestException:
            pass

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": f"{title}\n{message}"},
                timeout=10,
            )
        except requests.RequestException:
            pass


def scan_once(state: dict, silent_baseline: bool = False):
    today = date.today()
    dates = [(today + timedelta(days=i)).strftime("%Y%m%d") for i in range(DAYS_AHEAD)]
    print(f"--- 스캔 시작: {today.isoformat()} 기준 {DAYS_AHEAD}일치 확인 ---")

    for name, code in THEATERS.items():
        known = set(state.get(name, []))
        new_dates = []
        for ymd in dates:
            if ymd in known:
                continue
            if movie_imax_open(code, ymd):
                new_dates.append(ymd)
            time.sleep(0.3)

        if new_dates:
            if silent_baseline:
                print(f"  [기준선] {name}: {len(new_dates)}개 날짜 오픈 중 (알림 X)")
            else:
                pretty = ", ".join(f"{d[4:6]}/{d[6:]}" for d in new_dates)
                notify(
                    f"🎬 {MOVIE_KEYWORD or 'IMAX'} — CGV {name} 예매 오픈!",
                    f"새 상영 날짜: {pretty}\n지금 CGV 앱에서 예매하세요!",
                )
            known |= set(new_dates)
        else:
            print(f"  [확인 완료] {name}: 새로 오픈된 '{MOVIE_KEYWORD}' IMAX 날짜 없음 (기존 {len(known)}개 유지)")

        state[name] = sorted(d for d in known if d >= dates[0])

    save_state(state)


def main():
    once = "--once" in sys.argv
    state = load_state()
    first_run = all(not v for v in state.values()) and not os.path.exists(STATE_FILE)

    if first_run:
        print("첫 실행 → 현재 오픈된 날짜를 기준선으로 저장 (알림 X)")
        scan_once(state, silent_baseline=True)
        if once:
            return

    if once:
        scan_once(state)
        return

    print(f"'{MOVIE_KEYWORD}' IMAX 오픈 감시 시작 ({', '.join(THEATERS)}, {INTERVAL_SEC}초 주기)")
    while True:
        try:
            scan_once(state)
        except Exception as e:
            print(f"[스캔 오류] {e}")
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
