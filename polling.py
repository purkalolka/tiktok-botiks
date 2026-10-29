"""
Polling entry point for the same TikTok bot (v4 code in app.py).

Use this on an always-on free bot host such as FadeHost, where the
free tier runs a polling process but its web address sleeps (so a
webhook would not work there). All download logic is reused from
app.py unchanged: the same queue (one download at a time), the same
tikwm fast path, the same yt-dlp fallback, the same 48 MB cap.

Run:  BOT_TOKEN=<token from BotFather> python polling.py

On start this deletes any Telegram webhook (drop_pending_updates=true),
because Telegram will not deliver getUpdates while a webhook is set.
That is also why the Koyeb webhook bot must not run at the same time:
stop/pause the Koyeb service first, or this script's deleteWebhook
will silently take the webhook away from it. To go back to Koyeb,
stop this process and re-run set_webhook.sh from the Koyeb folder.

No token is stored in this file or in app.py; BOT_TOKEN comes only
from the environment (on FadeHost: the panel's environment variables).
"""

import os
import sys
import time

import requests

import app as bot  # noqa: F401  (reuses tg_send_*, job_queue, TIKTOK_RE)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
POLL_TIMEOUT = 30  # seconds of long-polling per getUpdates call


def delete_webhook(session):
    """Remove the webhook so getUpdates can work. Returns True on success."""
    try:
        resp = session.post(
            f"{TG_API}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=15,
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        ok = resp.status_code == 200 and data.get("ok", True)
        print(f"deleteWebhook -> {resp.status_code} {resp.text[:200]}", flush=True)
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"deleteWebhook failed: {exc}", flush=True)
        return False


def handle_message(session, message):
    """Mirror the Koyeb webhook handler's instant replies + queueing."""
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = message.get("text", "") or ""
    if text.strip() in ("/start", "/help"):
        bot.tg_send_message(
            chat_id,
            "Пришли ссылку на видео из TikTok — я скачаю его без водяного знака и пришлю сюда.",
        )
    elif not bot.TIKTOK_RE.search(text):
        bot.tg_send_message(chat_id, "Это не похоже на ссылку на TikTok. Пришли ссылку на видео.")
    else:
        queued = bot.job_queue.qsize()
        if queued:
            bot.tg_send_message(chat_id, f"Качаю… (в очереди перед тобой: {queued})")
        else:
            bot.tg_send_message(chat_id, "Качаю…")
        bot.job_queue.put({"chat_id": chat_id, "text": text})


def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN is not set. Set it in the host panel, do not put it in code.", flush=True)
        return 2
    session = requests.Session()
    if not delete_webhook(session):
        print("Could not delete the webhook — getUpdates will return 409 while a webhook is set. "
              "Check the token, then restart.", flush=True)
        return 1
    print("Polling started (long-polling, no webhook, no pinger needed).", flush=True)
    offset = None
    while True:
        try:
            params = {"timeout": POLL_TIMEOUT}
            if offset is not None:
                params["offset"] = offset
            resp = session.get(f"{TG_API}/getUpdates", params=params, timeout=POLL_TIMEOUT + 15)
            if resp.status_code == 409:
                print("getUpdates 409: a webhook is set again (or another bot instance is polling). "
                      "Stopping instead of fighting it.", flush=True)
                return 1
            if resp.status_code != 200:
                print(f"getUpdates HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
                time.sleep(5)
                continue
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message") or {}
                if message:
                    handle_message(session, message)
        except Exception as exc:  # noqa: BLE001 - polling loop must never die
            print(f"polling error: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
