import json
from pathlib import Path

import pytest

import worker

AUTH = {"Authorization": "Bearer secret"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "DEST", f"file://{tmp_path / 'dest'}")
    monkeypatch.setattr(worker, "FORMAT", "csv")
    monkeypatch.setattr(worker, "CRON_TOKEN", "secret")
    monkeypatch.setattr(worker, "BACKUP_TZ", "Asia/Tokyo")
    return worker.app.test_client()


def _stub_run_backup(monkeypatch):
    def fake(fmt, out):
        out = Path(out)
        (out / "collection.csv").write_text("a\n1\n", encoding="utf-8")
        (out / "wantlist.csv").write_text("b\n2\n", encoding="utf-8")
        return {
            "started_at": "s",
            "finished_at": "f",
            "format": fmt,
            "directory": str(out),
            "collection": 120,
            "wantlist": 3,
            "files": [],
        }

    monkeypatch.setattr(worker.discogs_backup, "run_backup", fake)


def test_healthz(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"X-Cron-Token": "wrong"}],
)
def test_run_requires_token(client, headers):
    assert client.post("/run", headers=headers).status_code == 401


def test_appengine_cron_header_is_trusted(client, monkeypatch):
    _stub_run_backup(monkeypatch)
    res = client.post("/run", headers={"X-Appengine-Cron": "true"})
    assert res.status_code == 200


def test_run_saves_files_and_manifest(client, monkeypatch, tmp_path):
    _stub_run_backup(monkeypatch)

    res = client.post("/run", headers=AUTH)

    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok"
    assert body["collection"] == 120
    assert body["wantlist"] == 3
    assert len(body["uploaded"]) == 3

    dest = tmp_path / "dest"
    run_dir = dest / body["key_prefix"]
    assert (run_dir / "collection.csv").is_file()
    assert (run_dir / "wantlist.csv").is_file()
    manifest = json.loads((dest / "latest.json").read_text(encoding="utf-8"))
    assert manifest["collection"] == 120
    assert manifest["wantlist"] == 3
    assert manifest["format"] == "csv"


def test_run_is_idempotent_within_the_day(client, monkeypatch):
    _stub_run_backup(monkeypatch)

    first = client.post("/run", headers=AUTH).get_json()
    second = client.post("/run", headers=AUTH).get_json()

    assert first["key_prefix"] == second["key_prefix"]


def test_run_returns_409_when_busy(client, monkeypatch):
    _stub_run_backup(monkeypatch)
    worker._lock.acquire()
    try:
        assert client.post("/run", headers=AUTH).status_code == 409
    finally:
        worker._lock.release()


def test_run_returns_500_for_invalid_format(client, monkeypatch):
    monkeypatch.setattr(worker, "FORMAT", "xml")

    res = client.post("/run", headers=AUTH)

    assert res.status_code == 500
    assert res.get_json()["status"] == "error"
    assert "csv / json / both" in res.get_json()["message"]


def test_job_mode_success(client, monkeypatch, capsys):
    _stub_run_backup(monkeypatch)

    assert worker.main(["job"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "ok"


def test_job_mode_invalid_format(monkeypatch, capsys):
    monkeypatch.setattr(worker, "FORMAT", "xml")

    assert worker.main(["job"]) == 2
    assert "BACKUP_FORMAT" in capsys.readouterr().err


def test_job_mode_reports_failure(monkeypatch, capsys):
    def boom(fmt, out):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker.discogs_backup, "run_backup", boom)

    assert worker.main(["job"]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"status": "error", "message": "boom"}
