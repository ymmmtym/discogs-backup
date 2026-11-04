"""Discogs API のローカルモック（テスト用）。外部ネットワークには出ない。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "test-token"
USER = "tester"
FIELDS = [
    {"id": 1, "name": "Media Condition"},
    {"id": 2, "name": "Sleeve Condition"},
]


def _basic(i: int) -> dict:
    return {
        "id": 1000 + i,
        "title": f"Title {i}",
        "artists": [{"name": f"Artist {i}"}],
        "year": 1990 + i % 30,
        "labels": [{"name": "Label X", "catno": f"CAT{i:03d}"}],
        "formats": [{"name": "Vinyl", "descriptions": ["LP"]}],
        "resource_url": f"https://api.discogs.com/releases/{1000 + i}",
        "cover_image": f"https://img.example/{i}.jpg",
    }


# 2 ページに跨る件数にしてページネーションを検証する
COLLECTION = [
    {
        "id": 1000 + i,
        "instance_id": 5000 + i,
        "folder_id": 1 + i % 3,
        "date_added": f"2024-01-{1 + i % 28:02d}T00:00:00-07:00",
        "rating": i % 6,
        # 偶数行はカスタムフィールド無し（行ごとのキー差異を再現）
        "notes": (
            [{"field_id": 1, "value": "NM"}, {"field_id": 2, "value": "VG+"}]
            if i % 2
            else []
        ),
        "basic_information": _basic(i),
    }
    for i in range(1, 121)
]

WANTS = [
    {
        "id": 9000 + i,
        "date_added": "2024-02-01T00:00:00-07:00",
        "rating": i,
        "notes": f"note {i}",
        "basic_information": _basic(i),
    }
    for i in range(1, 4)
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # テスト出力を汚さない
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Discogs-Ratelimit-Remaining", "60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server の API)
        if self.headers.get("Authorization") != f"Discogs token={TOKEN}":
            return self._send(401, {"message": "unauthorized"})

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        page = int(query.get("page", ["1"])[0])
        per_page = int(query.get("per_page", ["100"])[0])

        if parsed.path == f"/users/{USER}/collection/fields":
            return self._send(200, {"fields": FIELDS})
        if parsed.path == f"/users/{USER}/collection/folders/0/releases":
            return self._send(200, self._page(COLLECTION, "releases", page, per_page))
        if parsed.path == f"/users/{USER}/wants":
            return self._send(200, self._page(WANTS, "wants", page, per_page))
        return self._send(404, {"message": "not found"})

    @staticmethod
    def _page(items: list[dict], key: str, page: int, per_page: int) -> dict:
        pages = max(1, -(-len(items) // per_page))
        start = (page - 1) * per_page
        return {
            key: items[start : start + per_page],
            "pagination": {
                "page": page,
                "pages": pages,
                "per_page": per_page,
                "items": len(items),
            },
        }


def make_server(port: int = 0) -> ThreadingHTTPServer:
    """127.0.0.1 の空きポートでモックサーバを作る。"""
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
