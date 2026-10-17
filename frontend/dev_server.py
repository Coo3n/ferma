"""Сайт фермы отдельно от сервера.

Обычно сайт раздаёт сам сервер (backend), и этот файл не нужен. Он нужен,
когда сайт и API живут раздельно: сервер запущен с FARM_SERVE_FRONTEND=0
(чистый API), а сайт раздаётся отсюда — как в продакшене это делал бы nginx.

Всё, что начинается с /api, пересылается на сервер фермы как есть (включая
поток экрана), остальное — файлы из этой папки. Сайт ходит в API по
относительным адресам, поэтому ему всё равно, кто его раздаёт.

    python3 frontend/dev_server.py                  # сайт на :5173, API на :8777
    FARM_API=http://10.0.0.2:8777 python3 frontend/dev_server.py --port 8080

Только стандартная библиотека: зависимостей у сайта нет.
"""
from __future__ import annotations

import argparse
import http.client
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
API = os.getenv("FARM_API", "http://127.0.0.1:8777")
# Заголовки «одного прыжка» не пересылаются (RFC 9110, 7.6.1).
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
       "proxy-authorization", "proxy-authenticate", "te", "trailer"}


class Handler(SimpleHTTPRequestHandler):
    def _proxy(self) -> None:
        api = urlsplit(API)
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = self.rfile.read(length)
        # Host не трогаем: сервер сверяет Origin с Host (защита от чужих
        # страниц), а браузер видит адрес этого сайта, а не API.
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        conn = http.client.HTTPConnection(api.hostname, api.port or 80, timeout=600)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            # Поток экрана (MJPEG) бесконечный — отдаём кусками, а не целиком.
            while True:
                chunk = resp.read1(64 * 1024) if hasattr(resp, "read1") else resp.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass   # вкладку закрыли посреди потока — это нормально
        except OSError as e:
            self.send_error(502, f"сервер фермы недоступен ({API}): {e}")
        finally:
            conn.close()

    def _route(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
        elif self.command in ("GET", "HEAD"):
            super().do_GET() if self.command == "GET" else super().do_HEAD()
        else:
            self.send_error(405)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = _route

    def end_headers(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=str(HERE)))
    print(f"→ сайт: http://{args.host}:{args.port}  ·  API: {API}")
    server.serve_forever()


if __name__ == "__main__":
    main()
