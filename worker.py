"""クラウド非依存の実行エントリポイント。

同じイメージを各クラウドのトリガーから呼び出せるようにする。

    MODE=http   HTTP サーバとして起動（Cloud Run / GAE Flex / Azure Functions など）
    MODE=job    1 回だけ実行して終了（Cloud Run Jobs / ACA Jobs / ECS タスクなど）

環境変数:

    MODE          http（既定）/ job
    PORT          HTTP 待ち受けポート（既定 8080）
    BACKUP_FORMAT csv / json / both（既定 both）
    BACKUP_DEST   保存先 URI（例: gs://bucket/discogs）。未設定なら保存しない
    BACKUP_TZ     オブジェクトキーに使うタイムゾーン（既定 Asia/Tokyo）
    CRON_TOKEN    /run の共有トークン（任意）

`CRON_TOKEN` を設定しない場合、`/run` は呼び出し元の認証に委ねる
（Cloud Run では「認証が必要」でデプロイし、Cloud Scheduler に OIDC を付ける）。
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

import discogs_backup
import storage

MODE = os.environ.get("MODE", "http")
FORMAT = os.environ.get("BACKUP_FORMAT", "both").strip().lower()
DEST = os.environ.get("BACKUP_DEST", "")
BACKUP_TZ = os.environ.get("BACKUP_TZ", "Asia/Tokyo")
CRON_TOKEN = os.environ.get("CRON_TOKEN", "")

app = Flask(__name__)
_lock = threading.Lock()


def _is_authorized(req) -> bool:
    """App Engine cron ヘッダ、または共有トークンで認証する。"""
    if req.headers.get("X-Appengine-Cron") == "true":
        return True
    if not CRON_TOKEN:
        return True

    authorization = req.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    else:
        supplied = req.headers.get("X-Cron-Token", "")
    return hmac.compare_digest(supplied, CRON_TOKEN)


def _key_prefix() -> str:
    """保存キー（既定では JST の日付）。再実行時は同じキーを上書きする。"""
    now = datetime.now(ZoneInfo(BACKUP_TZ))
    return os.environ.get("BACKUP_KEY") or now.strftime("%Y-%m-%d")


def run_once() -> dict:
    """バックアップを 1 回実行する。多重実行はせず busy を返す。"""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "message": "別のバックアップが実行中です"}
    try:
        if not DEST:
            app.logger.warning(
                "BACKUP_DEST が未設定のため、取得したデータは保存されません"
            )
        with tempfile.TemporaryDirectory(prefix="discogs-backup-") as tmp:
            summary = discogs_backup.run_backup(FORMAT, Path(tmp))
            summary["status"] = "ok"

            if DEST:
                key_prefix = _key_prefix()
                manifest = {
                    "key_prefix": key_prefix,
                    "format": summary["format"],
                    "started_at": summary["started_at"],
                    "finished_at": summary["finished_at"],
                    "collection": summary["collection"],
                    "wantlist": summary["wantlist"],
                }
                summary["uploaded"] = storage.save_outputs(
                    Path(tmp), DEST, key_prefix, manifest
                )
                summary["key_prefix"] = key_prefix
                summary["dest"] = DEST
        return summary
    finally:
        _lock.release()


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/run", methods=["GET", "POST"])
def run():
    if not _is_authorized(request):
        return jsonify({"status": "unauthorized"}), 401
    try:
        summary = run_once()
    except Exception as e:  # 失敗時は 5xx を返してスケジューラに再試行させる
        app.logger.exception("backup failed")
        return jsonify({"status": "error", "message": str(e)}), 500
    status_code = 200 if summary.get("status") == "ok" else 409
    return jsonify(summary), status_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discogs バックアップの実行エントリポイント")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["http", "job"],
        default=MODE,
        help="http: サーバ起動（既定） / job: 1 回だけ実行",
    )
    args = parser.parse_args(argv)

    if FORMAT not in discogs_backup.FORMATS:
        print(
            f"エラー: BACKUP_FORMAT は {' / '.join(discogs_backup.FORMATS)} のいずれかです: {FORMAT!r}",
            file=sys.stderr,
        )
        return 2

    if args.mode == "job":
        try:
            summary = run_once()
        except Exception as e:  # 設定不備などはジョブ失敗として返す
            print(
                json.dumps(
                    {"status": "error", "message": str(e)}, ensure_ascii=False, indent=2
                )
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary.get("status") == "ok" else 1

    if not CRON_TOKEN:
        app.logger.warning(
            "CRON_TOKEN が未設定です。/run は呼び出し元の認証（例: Cloud Run の IAM）に依存します"
        )
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
