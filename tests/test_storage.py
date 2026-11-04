import json

import fsspec
import pytest

import storage


@pytest.mark.parametrize(
    ("dest", "expected"),
    [
        ("file:///tmp/x", ("file", "/tmp/x")),
        ("/tmp/x", ("file", "/tmp/x")),
        ("gs://bucket/prefix", ("gs", "bucket/prefix")),
        ("s3://bucket/prefix", ("s3", "bucket/prefix")),
        ("az://container/prefix", ("az", "container/prefix")),
    ],
)
def test_parse_dest(dest, expected):
    assert storage.parse_dest(dest) == expected


def _make_src(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "collection.csv").write_text("a\n1\n", encoding="utf-8")
    (src / "wantlist.csv").write_text("b\n2\n", encoding="utf-8")
    return src


def test_save_outputs_local(tmp_path):
    src = _make_src(tmp_path)
    dest = tmp_path / "dest"

    saved = storage.save_outputs(src, f"file://{dest}", "2026-01-02", {"k": 1})

    assert (dest / "2026-01-02" / "collection.csv").is_file()
    assert (dest / "2026-01-02" / "wantlist.csv").is_file()
    assert json.loads((dest / "latest.json").read_text(encoding="utf-8")) == {"k": 1}
    # マニフェストも戻り値に含める（リモート保存と同じ挙動）
    assert len(saved) == 3
    assert saved[-1].endswith("latest.json")


def test_save_outputs_requires_files(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="保存対象のファイルがありません"):
        storage.save_outputs(empty, f"file://{tmp_path / 'dest'}", "key")


def test_save_outputs_remote_scheme(tmp_path):
    """memory:// で fsspec 経由のリモート保存経路を検証する。"""
    src = _make_src(tmp_path)

    saved = storage.save_outputs(src, "memory://bucket/root", "2026-01-02", {"k": 2})

    assert saved == [
        "memory://bucket/root/2026-01-02/collection.csv",
        "memory://bucket/root/2026-01-02/wantlist.csv",
        "memory://bucket/root/latest.json",
    ]
    fs, root = fsspec.core.url_to_fs("memory://bucket/root")
    assert fs.exists(f"{root}/2026-01-02/collection.csv")
    with fs.open(f"{root}/latest.json", "rb") as f:
        assert json.loads(f.read().decode("utf-8")) == {"k": 2}
