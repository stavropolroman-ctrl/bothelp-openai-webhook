from flask import Flask, request, jsonify, render_template, session, redirect
from openai import OpenAI
import os, tempfile, requests, json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
CONTENT_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)) or os.getcwd(), "content.json")

USER_STORES = {}

# ── Content helpers ──────────────────────────────────────────────────────────

def load_content():
    with open(CONTENT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_content(data):
    with open(CONTENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── Landing page ─────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html", c=load_content())

# ── Admin panel ──────────────────────────────────────────────────────────────

@app.get("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/admin/login")
    return render_template("admin.html")

@app.get("/admin/login")
def admin_login_get():
    if session.get("admin"):
        return redirect("/admin")
    return render_template("admin_login.html", error=None)

@app.post("/admin/login")
def admin_login_post():
    if request.form.get("password", "") == ADMIN_PASSWORD:
        session["admin"] = True
        return redirect("/admin")
    return render_template("admin_login.html", error="Неверный пароль. Попробуйте снова.")

@app.get("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/admin/login")

# ── Content API ──────────────────────────────────────────────────────────────

@app.get("/api/content")
def api_get_content():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_content())

@app.post("/api/content")
def api_post_content():
    if not session.get("admin"):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    save_content(data)
    return jsonify({"ok": True})

# ── Existing webhook routes ───────────────────────────────────────────────────

@app.get("/cowork-replay")
def cowork_replay():
    html_path = os.path.join(os.path.abspath(os.path.dirname(__file__) or os.getcwd()), "cowork-replay.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}

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
    history  = data.get("history", "")

    prompt = f"{SYSTEM_PROMPT}\n\nКонтекст:\n{history}\n\nВопрос:\n{question}"

    resp = client.responses.create(
        model="gpt-4o-mini",
        tools=[{"type": "file_search", "vector_store_ids": [vs_id]}],
        input=prompt
    )
    return jsonify({"ok": True, "answer": resp.output_text})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
