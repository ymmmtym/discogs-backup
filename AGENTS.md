# AGENTS.md

Discogs のコレクション / ウォントリストをバックアップする Python アプリ。クラウド非依存のコンテナとして動かす。

## 構成

- `discogs_backup.py` — Discogs API 取得・CSV/JSON 生成。クラウド SDK を import しない
- `storage.py` — 保存先の抽象化（fsspec 経由で `file://` / `gs://` / `s3://` / `az://`）
- `worker.py` — `MODE=http`（サーバ）/ `MODE=job`（単発）の共通エントリポイント
- `Dockerfile` / `requirements*.txt` — `STORAGE_BACKEND=gcs|s3|azure` で保存先バックエンドを選択
- `infra/terraform/gcp/` — GCP（Cloud Run + Cloud Scheduler + GCS）用 Terraform

## ルール

- シークレット（Discogs のトークン等）はコミットしない。`.env` / `.mise.local.toml` は gitignore 済み
- 保存先やスケジュールの変更は環境変数と Terraform 変数で行い、アプリにクラウド固有処理を足さない
- 出力形式は `--format` / `BACKUP_FORMAT`（csv / json / both）
- ローカル実行の既定保存先は `./discogs_backups/`（`DISCOGS_BACKUP_DIR` で変更可）
- 動作確認は `python3 discogs_backup.py --format csv` と `python3 worker.py job`（`BACKUP_DEST` をローカルに）
- Terraform は `terraform fmt -recursive` と `terraform validate` を通すこと

## デプロイ

`infra/README.md` を参照。Terraform では secret の入れ物だけ作り、値は `gcloud secrets versions add` で投入する（state に残さない）。
