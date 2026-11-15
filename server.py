# Локальный запуск: python server.py, затем открыть http://localhost:8000
# Ключ Groq можно положить в файл .env рядом (строка GROQ_API_KEY=...) или в переменную окружения.
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
env = ROOT / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.strip() and not k.strip().startswith("#"):
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

import importlib.util  # noqa: E402
import sys  # noqa: E402


def load(name):
    for p in (ROOT / "api" / (name + ".py"), ROOT / (name + ".py")):
        if p.exists():
            spec = importlib.util.spec_from_file_location(name, p)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m
    sys.exit("Не найден файл %s.py: положи его в папку api рядом с server.py" % name)


# Файл загружается заново на каждый запрос, чтобы правки кода применялись
# без перезапуска сервера (локальная разработка; на Vercel код свежий при каждом деплое).
ROUTES = {"/api/ai": "ai", "/api/edupage": "edupage", "/api/photo": "photo"}


class H(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        out = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._json(200, {"ok": True})
        if path in ("/", "/index.html"):
            out = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        else:
            self._json(404, {"error": "Не найдено"})

    def do_POST(self):
        name = ROUTES.get(self.path)
        if not name:
            return self._json(404, {"error": "Не найдено"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except Exception:
            body = {}
        try:
            code, obj = load(name).run(self.headers, body)
        except Exception as e:
            traceback.print_exc()
            code, obj = 500, {"error": "Ошибка сервера: %s" % type(e).__name__}
        self._json(code, obj)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print("Открой в браузере: http://localhost:%d  (остановить: Ctrl+C)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
