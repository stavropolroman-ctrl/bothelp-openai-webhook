from flask import Flask, request, jsonify
from openai import OpenAI
import os, tempfile, requests

app = Flask(__name__)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TG_TOKEN = os.environ["TELEGRAM_TOKEN"]
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"

USER_STORES = {}

SYSTEM_PROMPT = (
    "Ты — репетитор по английскому языку. "
    "Отвечай кратко и чётко, ссылаясь на загруженные материалы. "
    "Если вопрос вне материалов — скажи об этом и помоги кратко."
)


def send_message(chat_id, text):
    requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text})


def ensure_vector_store(user_id):
    vs_id = USER_STORES.get(user_id)
    if not vs_id:
        vs = client.vector_stores.create(name=f"tg_{user_id}")
        vs_id = vs.id
        USER_STORES[user_id] = vs_id
    return vs_id


@app.post("/webhook")
def webhook():
    update = request.json
    message = update.get("message") or update.get("edited_message")
    if not message:
        return "ok"

    chat_id = message["chat"]["id"]
    user_id = str(message["from"]["id"])
    text = message.get("text", "")

    if text == "/start":
        send_message(
            chat_id,
            "👋 Привет! Я AI-репетитор по английскому языку.\n\n"
            "Отправьте учебный материал (PDF или документ) и задавайте вопросы по нему.",
        )
        return "ok"

    if "document" in message:
        doc = message["document"]
        file_name = doc.get("file_name", "file")
        send_message(chat_id, "⏳ Загружаю файл...")

        file_info = requests.get(f"{TG_API}/getFile?file_id={doc['file_id']}").json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TG_TOKEN}/{file_path}"

        ext = os.path.splitext(file_name)[1] or ".pdf"
        r = requests.get(file_url, timeout=60)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            f.write(r.content)
            path = f.name

        vs_id = ensure_vector_store(user_id)
        up = client.files.create(file=open(path, "rb"), purpose="assistants")
        client.vector_stores.files.create(vector_store_id=vs_id, file_id=up.id)

        send_message(chat_id, f"✅ Файл «{file_name}» загружен! Задавайте вопросы.")
        return "ok"

    if not text:
        return "ok"

    send_message(chat_id, "⏳ Думаю...")
    vs_id = ensure_vector_store(user_id)

    resp = client.responses.create(
        model="gpt-4o-mini",
        tools=[{"type": "file_search", "vector_store_ids": [vs_id]}],
        input=f"{SYSTEM_PROMPT}\n\nВопрос: {text}",
    )
    send_message(chat_id, resp.output_text)
    return "ok"


@app.post("/upload")
def upload():
    data = request.json
    user_id = str(data["user_id"])
    file_url = data["file_url"]
    vs_id = ensure_vector_store(user_id)

    r = requests.get(file_url, timeout=60)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
        f.write(r.content)
        path = f.name

    up = client.files.create(file=open(path, "rb"), purpose="assistants")
    client.vector_stores.files.create(vector_store_id=vs_id, file_id=up.id)
    return jsonify({"ok": True, "vector_store_id": vs_id})


@app.post("/ask")
def ask():
    data = request.json
    user_id = str(data["user_id"])
    vs_id = data.get("vector_store_id") or ensure_vector_store(user_id)
    question = data.get("question", "")

    resp = client.responses.create(
        model="gpt-4o-mini",
        tools=[{"type": "file_search", "vector_store_ids": [vs_id]}],
        input=f"{SYSTEM_PROMPT}\n\nВопрос: {question}",
    )
    return jsonify({"ok": True, "answer": resp.output_text})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
