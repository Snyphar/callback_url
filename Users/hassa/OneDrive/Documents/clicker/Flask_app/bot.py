import os
import time
import requests

TOKEN = "9166168045:AAHG_zwrlfviXQtmbGuXuR44Bhn7EtYSIKU"
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


def api(method, **payload):
    response = requests.post(
        f"{BASE_URL}/{method}",
        json=payload,
        timeout=40,
    )
    response.raise_for_status()
    data = response.json()

    if not data["ok"]:
        raise RuntimeError("Telegram API request failed")

    return data["result"]


def main():
    offset = 0
    print("Bot running. Press Ctrl+C to stop.")

    while True:
        try:
            updates = api(
                "getUpdates",
                offset=offset,
                timeout=30,
                allowed_updates=["message"],
            )

            for update in updates:
                message = update.get("message", {})
                print(message.get("chat", {}))
                text = message.get("text", "")
                command = text.split(maxsplit=1)[0] if text else ""

                if command.split("@")[0] == "/start":
                    api(
                        "sendMessage",
                        chat_id=message["chat"]["id"],
                        text="Hello! 👋",
                    )

                offset = update["update_id"] + 1

        except (requests.RequestException, RuntimeError):
            print("Connection or API error. Retrying...")
            time.sleep(3)
        
    

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped.")