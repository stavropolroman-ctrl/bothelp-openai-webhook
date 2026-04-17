from flask import Flask, request
import os, requests

app = Flask(__name__)
TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"


def send_message(chat_id, text):
    requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text})


@app.post("/webhook")
def webhook():
    message = request.json.get("message")
    if not message:
        return "ok"
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    if text:
        send_message(chat_id, text)
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
