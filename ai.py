# Объяснения и тесты через Groq API. Ключ только в переменной окружения GROQ_API_KEY.
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

PROMPTS = {
    "note": "Составь короткий понятный конспект по теме для школьника 8 класса: главное, определения, 1-2 примера. Пиши по-русски.",
    "test": "Составь мини-тест из 5 вопросов по теме с вариантами ответов. Правильные ответы дай в конце списком. Пиши по-русски.",
    "simple": "Объясни тему простыми словами, как другу. Если текст на английском или кыргызском, переведи ключевые слова на русский и объясни. Пиши по-русски.",
}


def run(headers, body):
    need = os.environ.get("APP_PASSWORD")
    if need and headers.get("x-pass") != need:
        return 401, {"error": "Неверный пароль приложения"}
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return 500, {"error": "Не задан GROQ_API_KEY"}
    task, text = body.get("task"), body.get("text")
    if task not in PROMPTS or not text:
        return 400, {"error": "Неверный запрос"}
    payload = json.dumps({
        "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "temperature": 0.4,
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": PROMPTS[task]},
            {"role": "user", "content": "Предмет: %s\nТема: %s" % (str(body.get("subject", ""))[:80], str(text)[:1500])},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "study-helper/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.load(r)
        return 200, {"text": d["choices"][0]["message"]["content"]}
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        return 502, {"error": "Groq: " + (msg or str(e.code))}
    except Exception as e:
        return 502, {"error": "Не удалось связаться с Groq (" + type(e).__name__ + ")"}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except Exception:
            body = {}
        code, obj = run(self.headers, body)
        out = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
