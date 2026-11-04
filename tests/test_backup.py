import csv
import json
from pathlib import Path

import pytest

RESTORE_COLUMNS = [
    "release_id",
    "folder_id",
    "instance_id",
    "rating",
    "Media Condition",
    "Sleeve Condition",
]


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_fetches_all_pages(backup_env, tmp_path):
    summary = backup_env.run_backup("both", tmp_path / "out")

    assert summary["collection"] == 120
    assert summary["wantlist"] == 3
    assert len(summary["files"]) == 4


def test_csv_has_restore_columns(backup_env, tmp_path):
    out = tmp_path / "out"
    backup_env.run_backup("csv", out)

    rows = _read_csv(out / "collection.csv")
    assert len(rows) == 120
    for column in RESTORE_COLUMNS:
        assert column in rows[0]

    # カスタムフィールドが無い行は空欄（以前は KeyError/ValueError になっていた）
    assert rows[0]["Media Condition"] == "NM"
    assert rows[1]["Media Condition"] == ""


def test_wantlist_csv(backup_env, tmp_path):
    out = tmp_path / "out"
    backup_env.run_backup("csv", out)

    rows = _read_csv(out / "wantlist.csv")
    assert len(rows) == 3
    assert rows[0]["notes"] == "note 1"
    assert rows[0]["rating"] == "1"


def test_json_output(backup_env, tmp_path):
    out = tmp_path / "out"
    backup_env.run_backup("json", out)

    collection = json.loads((out / "collection.json").read_text(encoding="utf-8"))
    wantlist = json.loads((out / "wantlist.json").read_text(encoding="utf-8"))
    assert len(collection) == 120
    assert len(wantlist) == 3
    assert not (out / "collection.csv").exists()


def test_cli_backup_updates_latest_symlink(backup_env):
    summary = backup_env.backup("csv")

    latest = backup_env.BACKUP_DIR / "latest"
    assert latest.is_symlink()
    assert latest.resolve() == Path(summary["directory"]).resolve()
    assert (latest / "collection.csv").is_file()


@pytest.mark.parametrize("existing", ["symlink", "file"])
def test_cli_backup_replaces_existing_latest(backup_env, existing):
    backup_env.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stale = backup_env.BACKUP_DIR / "stale"
    stale.mkdir()
    latest = backup_env.BACKUP_DIR / "latest"
    if existing == "symlink":
        latest.symlink_to(stale)
    else:
        latest.write_text("stale", encoding="utf-8")

    summary = backup_env.backup("csv")

    assert latest.is_symlink()
    assert latest.resolve() == Path(summary["directory"]).resolve()


@pytest.mark.parametrize("fmt", ["xml", "", "csv,json"])
def test_invalid_format_raises(backup_env, tmp_path, fmt):
    with pytest.raises(ValueError, match="csv / json / both"):
        backup_env.run_backup(fmt, tmp_path / "out")


def test_format_is_normalized(backup_env, tmp_path):
    summary = backup_env.run_backup("CSV", tmp_path / "out")
    assert summary["format"] == "csv"


def test_missing_credentials_raises(backup_env, monkeypatch, tmp_path):
    monkeypatch.setattr(backup_env, "DISCOGS_USERNAME", "")
    with pytest.raises(RuntimeError, match="DISCOGS_PERSONAL_ACCESS_TOKEN"):
        backup_env.run_backup("csv", tmp_path / "out")
