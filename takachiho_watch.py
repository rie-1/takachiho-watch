#!/usr/bin/env python3
"""高千穂峡貸しボート 空き通知（2026/12/3・12/4 対象）

準備:
  pip install playwright && playwright install chromium
通知先（使うものだけ環境変数を設定。複数同時もOK）:
  [メール]    MAIL_USER=送信元Gmail  MAIL_PASS=Googleアプリパスワード  MAIL_TO=宛先
  [Telegram]  TELEGRAM_TOKEN=BotFatherで取得  TELEGRAM_CHAT_ID=自分のchat id
  [Discord]   DISCORD_WEBHOOK=Webhook URL
  [ntfy]      NTFY_TOPIC=推測されにくい任意名
実行:
  python takachiho_watch.py            # 1回チェック（cron等で定期実行）
  python takachiho_watch.py --debug    # HTML/スクショ保存
"""
import json, os, smtplib, sys, urllib.parse, urllib.request
from email.message import EmailMessage
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://eipro.jp/takachiho1/eventCalendars/index"
WEEKS = int(os.getenv("WEEKS", "3"))
TARGETS = [d for d in os.getenv("TARGET_DATES", "2026-12-03,2026-12-04").split(",") if d]
STATE = Path(__file__).with_name("state.json")
SOLD_MARKS = ("×", "✕", "⌛", "⏳", "満", "締")
DEBUG = "--debug" in sys.argv

JS_COLLECT = """() => {
  const heads = [...document.querySelectorAll('.fc-day-header[data-date]')]
    .map(h => ({d: h.dataset.date, r: h.getBoundingClientRect()}));
  return [...document.querySelectorAll('.fc-event')].map(e => {
    const r = e.getBoundingClientRect(), cx = r.left + r.width / 2;
    const h = heads.find(h => cx >= h.r.left && cx <= h.r.right);
    return {date: h ? h.d : '?', text: e.innerText.replace(/\\s+/g, ' ').trim()};
  });
}"""


def post(url, data, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    urllib.request.urlopen(req, timeout=15).read()


def notify(msg: str, subject="高千穂峡ボートに空きが出ました"):
    print(msg)
    if os.getenv("MAIL_USER") and os.getenv("MAIL_PASS"):
        m = EmailMessage()
        m["Subject"], m["From"] = subject, os.environ["MAIL_USER"]
        m["To"] = os.getenv("MAIL_TO", os.environ["MAIL_USER"])
        m.set_content(msg)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
            s.login(os.environ["MAIL_USER"], os.environ["MAIL_PASS"])
            s.send_message(m)
    if os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage",
             urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": msg}).encode())
    if os.getenv("DISCORD_WEBHOOK"):
        post(os.environ["DISCORD_WEBHOOK"], json.dumps({"content": msg}).encode(),
             {"Content-Type": "application/json"})
    if t := os.getenv("NTFY_TOPIC"):
        post(f"https://ntfy.sh/{t}", msg.encode(), {"Priority": "high", "Click": URL})


def scrape() -> dict:
    slots = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1400, "height": 1000}, locale="ja-JP")
        page.goto(URL, wait_until="networkidle")
        page.get_by_text("週", exact=True).first.click()
        page.wait_for_timeout(1500)
        for i in range(WEEKS):
            page.wait_for_selector(".fc-event, .fc-day-header", timeout=15000)
            page.wait_for_timeout(800)
            if DEBUG:
                Path(f"debug_week{i}.html").write_text(page.content(), encoding="utf-8")
                page.screenshot(path=f"debug_week{i}.png", full_page=True)
            for ev in page.evaluate(JS_COLLECT):
                slots[f"{ev['date']} {ev['text']}"] = not any(m in ev["text"] for m in SOLD_MARKS)
            page.locator(".fc-next-button").first.click()
        b.close()
    return slots


def main():
    now = scrape()
    if not now:
        notify("⚠ 枠を1件も取得できませんでした。サイト構造が変わった可能性があります。", "高千穂峡ボート監視エラー")
        return
    old = json.loads(STATE.read_text()) if STATE.exists() else {}
    STATE.write_text(json.dumps(now, ensure_ascii=False, indent=1))
    target_slots = {k: ok for k, ok in now.items() if k[:10] in TARGETS}
    print(f"取得 {len(now)} 枠 / 対象日の枠 {len(target_slots)} / 対象日の空き {sum(target_slots.values())}")
    # 対象日で「前回は空きでなかった(または未登録)のに今回は空き」の枠だけ通知
    newly_open = [k for k, ok in target_slots.items() if ok and not old.get(k, False)]
    if newly_open:
        notify("空きが出ました！\n" + "\n".join(newly_open) + f"\n\n予約: {URL}")


if __name__ == "__main__":
    main()
