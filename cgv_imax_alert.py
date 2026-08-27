# -*- coding: utf-8 -*-
"""
CGV 용산/왕십리 '오디세이' IMAX 예매 오픈 알림
- 새로운 날짜에 오디세이 IMAX 상영이 열리면 텔레그램/데스크톱 알림

로컬 실행:   python cgv_imax_alert.py          (5분마다 무한 폴링)
GitHub Actions: python cgv_imax_alert.py --once  (1회 체크 후 종료)

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import json
import os
import re
import sys
import time
from datetime import date, timedelta

import requests

MOVIE_KEYWORD = "오디세이"   # 빈 문자열("")이면 모든 IMAX 상영 감지
THEATERS = {"용산아이파크몰": "0013", "왕십리": "0074"}
AREA_CODE = "01"
DAYS_AHEAD = 21
INTERVAL_SEC = 300
STATE_FILE = "imax_state.json"

URL = "http://www.cgv.co.kr/common/showtimes/iframeTheater.aspx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "http://www.cgv.co.kr/theaters/",
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
    """해당 날짜에 (키워드 영화의) IMAX 상영이 있는지"""
    params = {"areacode": AREA_CODE, "theatercode": theater_code, "date": ymd}
    try:
        r = requests.get(URL, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [요청 실패] {ymd}: {e}")
        return False

    # 영화별 블록(col-times)으로 쪼개서 키워드+IMAX 동시 포함 여부 확인
    blocks = re.split(r'class="col-times"', r.text)
    for block in blocks[1:]:
        if MOVIE_KEYWORD in block and "IMAX" in block.upper():
            return True
    return False


def notify(title: str, message: str):
    print(f"\n🔔 {title}\n{message}\n")
    try:
        from plyer import notification  # 로컬 데스크톱용, Actions에선 무시됨
        notification.notify(title=title, message=message, timeout=10)
    except Exception:
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

    for name, code in THEATERS.items():
        known = set(state.get(name, []))
        new_dates = []
        for ymd in dates:
            if ymd in known:
                continue
            if movie_imax_open(code, ymd):
                new_dates.append(ymd)
            time.sleep(0.5)

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

    print(f"'{MOVIE_KEYWORD}' IMAX 오픈 감시 시작 (용산/왕십리, {INTERVAL_SEC}초 주기)")
    while True:
        try:
            scan_once(state)
        except Exception as e:
            print(f"[스캔 오류] {e}")
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
