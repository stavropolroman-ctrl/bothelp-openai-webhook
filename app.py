from flask import Flask, request, jsonify, render_template
from openai import OpenAI
import os, tempfile, requests, csv, threading
from datetime import datetime

app = Flask(__name__)

_signups_lock = threading.Lock()
SIGNUPS_FILE = os.environ.get("SIGNUPS_FILE", "signups.csv")
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

USER_STORES = {}

# ── Subscription page ──────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "invalid email"}), 400

    name  = (data.get("name") or "").strip()
    level = (data.get("level") or "").strip()
    ts    = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    with _signups_lock:
        write_header = not os.path.exists(SIGNUPS_FILE)
        with open(SIGNUPS_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(["timestamp", "email", "name", "level"])
            w.writerow([ts, email, name, level])

    return jsonify({"ok": True})

@app.get("/signups")
def list_signups():
    secret = os.environ.get("ADMIN_SECRET")
    if secret and request.args.get("secret") != secret:
        return jsonify({"error": "forbidden"}), 403

    rows = []
    if os.path.exists(SIGNUPS_FILE):
        with open(SIGNUPS_FILE, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return jsonify({"count": len(rows), "signups": rows})

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