"""バックアップ出力の保存先を抽象化する（ローカル / GCS / S3 / Azure Blob）。

fsspec 経由なので、`BACKUP_DEST` のスキームを変えるだけで保存先を切り替えられる。
クラウド固有の SDK 呼び出しはここに閉じ込め、バックアップ本体は保存先を知らない。

    file:///path/to/dir  （または ./dir のようなスキームなしパス）
    gs://bucket/prefix
    s3://bucket/prefix
    az://container/prefix

保存レイアウト:

    <dest>/<key_prefix>/collection.csv
    <dest>/<key_prefix>/wantlist.csv
    <dest>/latest.json                # 最新実行のサマリ
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

MANIFEST_NAME = "latest.json"
LOCAL_SCHEMES = ("", "file")


def _manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")


def parse_dest(dest: str) -> tuple[str, str]:
    """保存先 URI を (スキーム, パス) に分解する。スキームなしはローカル扱い。"""
    parsed = urlparse(dest)
    if parsed.scheme in LOCAL_SCHEMES:
        path = dest[len("file://") :] if dest.startswith("file://") else dest
        return "file", path
    return parsed.scheme, f"{parsed.netloc}{parsed.path}"


def _backend_hint(scheme: str) -> str:
    return {
        "gs": "gcsfs",
        "s3": "s3fs",
        "az": "adlfs",
        "abfs": "adlfs",
    }.get(scheme, "fsspec の該当バックエンド")


def _url_to_fs(dest: str):
    import fsspec

    scheme, _ = parse_dest(dest)
    try:
        return fsspec.core.url_to_fs(dest)
    except ImportError as e:  # バックエンド未インストール
        raise RuntimeError(
            f"保存先 '{scheme}://' を使うには {_backend_hint(scheme)} が必要です: {e}"
        ) from e


def save_outputs(
    local_dir: Path,
    dest: str,
    key_prefix: str,
    manifest: dict | None = None,
) -> list[str]:
    """local_dir 内のファイルを dest/key_prefix/ に保存し、保存先の一覧を返す。"""
    local_dir = Path(local_dir)
    files = sorted(p for p in local_dir.iterdir() if p.is_file())
    if not files:
        raise RuntimeError(f"保存対象のファイルがありません: {local_dir}")

    scheme, path = parse_dest(dest)
    saved: list[str] = []

    if scheme == "file":
        target = Path(path).expanduser() / key_prefix
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, target / f.name)
            saved.append(str(target / f.name))
        if manifest is not None:
            root = Path(path).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            manifest_path = root / MANIFEST_NAME
            manifest_path.write_bytes(_manifest_bytes(manifest))
            saved.append(str(manifest_path))
        return saved

    fs, root = _url_to_fs(dest)
    base = f"{root.rstrip('/')}/{key_prefix}"
    fs.makedirs(base, exist_ok=True)
    for f in files:
        remote = f"{base}/{f.name}"
        fs.put_file(str(f), remote)
        saved.append(f"{scheme}://{remote.lstrip('/')}")

    if manifest is not None:
        manifest_uri = f"{root.rstrip('/')}/{MANIFEST_NAME}"
        with fs.open(manifest_uri, "wb") as fh:
            fh.write(_manifest_bytes(manifest))
        saved.append(f"{scheme}://{manifest_uri.lstrip('/')}")

    return saved
