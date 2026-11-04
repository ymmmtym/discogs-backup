#!/usr/bin/env python3
"""
Discogs Collection & Wantlist Backup Script
============================================
自分のDiscogsコレクションとウォントリストをJSONとCSVでバックアップします。

【準備】
1. Discogsにログイン → Settings → Developers → "Generate new token" で
   Personal Access Token を取得
2. 環境変数を設定するか、.envファイルを作成する
3. 保存先を変えたい場合は環境変数 DISCOGS_BACKUP_DIR を設定
   （デフォルト: 実行ディレクトリ直下の discogs_backups）
4. 定期実行したい場合は cron (Mac/Linux) や Task Scheduler (Windows) に登録

【環境変数の設定方法】

  Mac/Linux (.bashrc / .zshrc に追記):
    export DISCOGS_PERSONAL_ACCESS_TOKEN="your_token_here"
    export DISCOGS_USERNAME="your_username"

  Windows (PowerShell):
    $env:DISCOGS_PERSONAL_ACCESS_TOKEN="your_token_here"
    $env:DISCOGS_USERNAME="your_username"

  Windows (コマンドプロンプト):
    set DISCOGS_PERSONAL_ACCESS_TOKEN=your_token_here
    set DISCOGS_USERNAME=your_username

【.envファイルの方法】
  スクリプトと同じフォルダに .env ファイルを作成:
    DISCOGS_PERSONAL_ACCESS_TOKEN=your_token_here
    DISCOGS_USERNAME=your_username

【使い方】
    python3 discogs_backup.py                # CSV と JSON の両方（既定）
    python3 discogs_backup.py --format csv   # CSV のみ
    python3 discogs_backup.py --format json  # JSON のみ

【出力ファイル】
    保存先: 実行ディレクトリ直下の discogs_backups/<timestamp>/
    （環境変数 DISCOGS_BACKUP_DIR で変更可能）

    collection.json / collection.csv  ... コレクション
    wantlist.json   / wantlist.csv    ... ウォントリスト

    出力形式は --format で選択できます（既定: both）。
    CSV と JSON は同じフィールド構成です。CSV はリストアに使えるよう、
    release_id / folder_id / instance_id /
    rating / カスタムフィールド（Media Condition など）を含みます。
    リストア時は release_id（とコレクションなら folder_id）を
    Discogs API に渡してください。

【定期実行例 (cron)】
    # 毎週日曜日の午前3時に実行（保存先は実行ディレクトリ基準なので cd する）
    0 3 * * 0 cd /path/to && /usr/bin/python3 discogs_backup.py >> discogs_backup.log 2>&1
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

# ==================== 設定 ====================
# 環境変数を優先し、未設定なら .env ファイルから読み込む
DISCOGS_PERSONAL_ACCESS_TOKEN = os.environ.get("DISCOGS_PERSONAL_ACCESS_TOKEN", "")
DISCOGS_USERNAME = os.environ.get("DISCOGS_USERNAME", "")
# 保存先ルート（デフォルト: 実行ディレクトリ直下の discogs_backups）
BACKUP_DIR = Path(os.environ.get("DISCOGS_BACKUP_DIR", "discogs_backups")).expanduser()
# ==============================================


def load_dotenv():
    """.envファイルがあれば環境変数として読み込む（python-dotenv不要）。"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")  # クォート除去
                if key and key not in os.environ:
                    os.environ[key] = value


# .envファイルを読み込み（環境変数未設定時にフォールバック）
load_dotenv()
DISCOGS_PERSONAL_ACCESS_TOKEN = os.environ.get("DISCOGS_PERSONAL_ACCESS_TOKEN", DISCOGS_PERSONAL_ACCESS_TOKEN)
DISCOGS_USERNAME = os.environ.get("DISCOGS_USERNAME", DISCOGS_USERNAME)

API_BASE = "https://api.discogs.com"
FORMATS = ("csv", "json", "both")


def api_get(path: str, params: dict | None = None) -> dict:
    """Discogs API にGETリクエストを送り、JSONを返す。"""
    query = f"?{urlencode(params)}" if params else ""
    url = f"{API_BASE}{path}{query}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Discogs token={DISCOGS_PERSONAL_ACCESS_TOKEN}",
            "User-Agent": "DiscogsBackupScript/1.0",
        },
    )

    with urllib.request.urlopen(req) as response:
        remaining = response.headers.get("X-Discogs-Ratelimit-Remaining")
        if remaining and int(remaining) < 5:
            print(f"  Rate limit 残り {remaining}、1秒待機...")
            time.sleep(1)

        return json.loads(response.read().decode("utf-8"))


def fetch_all_pages(path: str, params: dict | None = None) -> list[dict]:
    """ページネーションを自動処理して全件取得。"""
    all_items = []
    page = 1
    per_page = 100

    while True:
        p = {"page": page, "per_page": per_page}
        if params:
            p.update(params)

        print(f"  Fetching {path} page={page}...")
        data = api_get(path, p)

        key = None
        for k in ("releases", "wants"):
            if k in data:
                key = k
                break

        if not key:
            break

        items = data[key]
        if not items:
            break

        all_items.extend(items)

        pagination = data.get("pagination", {})
        pages = pagination.get("pages", page)
        print(f"    -> got {len(items)} items (total fetched: {len(all_items)})")

        if page >= pages:
            break
        page += 1
        time.sleep(0.5)

    return all_items


def rating_of(item: dict) -> str:
    """rating フィールドを文字列で返す（dict / int どちらでも対応）。"""
    rating = item.get("rating", "")
    if isinstance(rating, dict):
        rating = rating.get("value", "")
    return "" if rating is None else str(rating)


def release_info(item: dict) -> dict:
    """basic_information から表示・照合用のフィールドを抽出。"""
    release = item.get("basic_information", item)

    artists = release.get("artists", [])
    artist_names = ", ".join(a.get("name", "") for a in artists)

    formats = release.get("formats", [])
    format_names = ", ".join(
        " ".join([f.get("name", ""), *f.get("descriptions", [])]).strip() for f in formats
    )

    labels = release.get("labels", [])
    label_names = ", ".join(l.get("name", "") for l in labels)
    catnos = ", ".join(l.get("catno", "") for l in labels if l.get("catno"))

    return {
        "title": release.get("title", ""),
        "artists": artist_names,
        "year": release.get("year", ""),
        "labels": label_names,
        "catno": catnos or release.get("catno", ""),
        "formats": format_names,
        "resource_url": release.get("resource_url", ""),
        "cover_image": release.get("cover_image", ""),
    }


def fetch_collection_fields() -> list[dict]:
    """コレクションのカスタムフィールド定義を取得（失敗時は空リスト）。"""
    try:
        return api_get(f"/users/{DISCOGS_USERNAME}/collection/fields").get("fields", [])
    except urllib.error.HTTPError as e:
        print(f"  警告: カスタムフィールド定義の取得に失敗しました ({e.code})")
        return []


def collection_row(item: dict, fields: list[dict]) -> dict:
    """コレクション1件を、リストアに必要な情報を含む行に変換。"""
    row = {
        "release_id": item.get("id", ""),
        "folder_id": item.get("folder_id", ""),
        "instance_id": item.get("instance_id", ""),
        "date_added": item.get("date_added", ""),
        "rating": rating_of(item),
    }

    # カスタムフィールド（Media Condition など）は列として展開する
    values: dict = {}
    notes = item.get("notes")
    if isinstance(notes, list):
        for note in notes:
            if isinstance(note, dict):
                values[note.get("field_id")] = note.get("value", "")

    for field in fields:
        name = field.get("name") or f"field_{field.get('id')}"
        row[name] = values.pop(field.get("id"), "")
    for field_id, value in values.items():
        row[f"field_{field_id}"] = value

    row.update(release_info(item))
    return row


def wantlist_row(item: dict) -> dict:
    """ウォントリスト1件を、リストアに必要な情報を含む行に変換。"""
    notes = item.get("notes")
    row = {
        "release_id": item.get("id", ""),
        "date_added": item.get("date_added", ""),
        "rating": rating_of(item),
        "notes": notes if isinstance(notes, str) else "",
    }
    row.update(release_info(item))
    return row


def save_json(data: list[dict], filepath: Path) -> Path:
    """JSONファイルに保存。"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Saved JSON: {filepath}")
    return filepath


def save_csv(data: list[dict], filepath: Path) -> Path | None:
    """CSVファイルに保存。"""
    if not data:
        print(f"  No data to save for CSV: {filepath}")
        return None

    # 行ごとにキーが異なる場合（カスタムフィールド定義の取得失敗など）でも
    # 欠落しないよう、全行のキーの和集合を初出順で列にする
    fieldnames = list(dict.fromkeys(key for row in data for key in row))
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"  Saved CSV:  {filepath}")
    return filepath


def run_backup(fmt: str = "both", out_dir: Path | None = None) -> dict:
    """Discogs から取得して out_dir に保存し、サマリを返す。

    クラウド実行時は out_dir に一時ディレクトリを渡し、呼び出し側で
    ストレージへ転送する（この関数はクラウド SDK に依存しない）。
    """
    fmt = str(fmt).strip().lower()
    if fmt not in FORMATS:
        raise ValueError(
            f"format は {' / '.join(FORMATS)} のいずれかです: {fmt!r}"
        )

    if not DISCOGS_PERSONAL_ACCESS_TOKEN or not DISCOGS_USERNAME:
        raise RuntimeError(
            "環境変数 DISCOGS_PERSONAL_ACCESS_TOKEN と DISCOGS_USERNAME を設定してください。"
        )

    if out_dir is None:
        out_dir = BACKUP_DIR / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"\n=== Discogs Backup started at {started_at} ===")
    print(f"Backup directory: {out_dir}\n")

    files: list[str] = []

    # --- Collection ---
    print("[1/2] Fetching Collection...")
    fields = fetch_collection_fields()
    collection_raw = fetch_all_pages(f"/users/{DISCOGS_USERNAME}/collection/folders/0/releases")
    collection = [collection_row(item, fields) for item in collection_raw]
    if fmt in ("json", "both"):
        files.append(str(save_json(collection, out_dir / "collection.json")))
    if fmt in ("csv", "both"):
        saved = save_csv(collection, out_dir / "collection.csv")
        if saved:
            files.append(str(saved))
    print(f"  Collection: {len(collection)} items\n")

    # --- Wantlist ---
    print("[2/2] Fetching Wantlist...")
    wantlist_raw = fetch_all_pages(f"/users/{DISCOGS_USERNAME}/wants")
    wantlist = [wantlist_row(item) for item in wantlist_raw]
    if fmt in ("json", "both"):
        files.append(str(save_json(wantlist, out_dir / "wantlist.json")))
    if fmt in ("csv", "both"):
        saved = save_csv(wantlist, out_dir / "wantlist.csv")
        if saved:
            files.append(str(saved))
    print(f"  Wantlist: {len(wantlist)} items\n")

    finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "format": fmt,
        "directory": str(out_dir),
        "collection": len(collection),
        "wantlist": len(wantlist),
        "files": files,
    }


def backup(fmt: str = "both"):
    """CLI 用: ローカルの BACKUP_DIR に保存し、latest リンクを更新する。"""
    try:
        summary = run_backup(fmt)
    except RuntimeError as e:
        print(f"エラー: {e}")
        print("")
        print("設定例:")
        print('  export DISCOGS_PERSONAL_ACCESS_TOKEN="your_token_here"')
        print('  export DISCOGS_USERNAME="your_username"')
        print("")
        print("または、スクリプトと同じフォルダに .env ファイルを作成してください。")
        sys.exit(1)

    backup_dir = Path(summary["directory"])

    # --- latest symlink ---
    latest_link = BACKUP_DIR / "latest"
    if latest_link.is_symlink() or latest_link.is_file():
        latest_link.unlink()
    try:
        # 相対パスだと latest 自身の位置基準になり壊れるため絶対パスで張る
        latest_link.symlink_to(backup_dir.resolve())
    except OSError:
        # symlink を作れない環境（Windows の権限不足など）ではパスを書き出す
        latest_link.write_text(str(backup_dir.resolve()), encoding="utf-8")

    print(f"=== Backup complete: {backup_dir} ===")
    print(f"Latest backup: {latest_link}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Discogs のコレクションとウォントリストをバックアップします。"
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["csv", "json", "both"],
        default="both",
        help="出力形式（既定: both）",
    )
    args = parser.parse_args()
    backup(args.format)
