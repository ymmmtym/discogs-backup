import threading

import pytest

from tests.mock_discogs import make_server


@pytest.fixture(scope="session")
def mock_api():
    """Discogs API のモックを空きポートで起動し、ベース URL を返す。"""
    server = make_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def backup_env(monkeypatch, tmp_path, mock_api):
    """discogs_backup のモジュール設定をテスト用に差し替える。"""
    import discogs_backup

    monkeypatch.setattr(discogs_backup, "API_BASE", mock_api)
    monkeypatch.setattr(discogs_backup, "DISCOGS_PERSONAL_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(discogs_backup, "DISCOGS_USERNAME", "tester")
    monkeypatch.setattr(discogs_backup, "BACKUP_DIR", tmp_path / "backups")
    return discogs_backup
