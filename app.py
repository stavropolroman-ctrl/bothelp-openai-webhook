from flask import Flask, request, jsonify, send_from_directory
from openai import OpenAI
import os, tempfile, requests

app = Flask(__name__)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

USER_STORES = {}

@app.get("/cowork-replay")
def cowork_replay():
    base = os.path.abspath(os.path.dirname(__file__)) or os.getcwd()
    return send_from_directory(base, "cowork-replay.html")

SYSTEM_PROMPT = (
  "Ты — преподаватель американского английского языка. "
  "Отвечай кратко, чётко, ссылаясь на материалы. "
  "Если вопрос вне материалов — скажи об этом и помоги кратко."
)

def ensure_vector_store(user_id):
    vs_id = USER_STORES.get(user_id)
    if not vs_id:
        vs = client.vector_stores.create(name=f"tg_{user_id}")
        vs_id = vs.id
        USER_STORES[user_id] = vs_id
    return vs_id

@app.post("/upload")
def upload():
    data = request.json
    user_id = str(data["user_id"])
    file_url = data["file_url"]
    vs_id = ensure_vector_store(user_id)

    r = requests.get(file_url, timeout=60)
    with tempfile.NamedTemporaryFile(delete=False) as f:
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
    history = data.get("history", "")

    prompt = f"{SYSTEM_PROMPT}\n\nКонтекст:\n{history}\n\nВопрос:\n{question}"

    resp = client.responses.create(
        model="gpt-4o-mini",
        tools=[{"type": "file_search", "vector_store_ids": [vs_id]}],
        input=prompt
    )
    return jsonify({"ok": True, "answer": resp.output_text})