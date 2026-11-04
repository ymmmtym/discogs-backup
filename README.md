# Discogs Backup

Discogs のコレクションとウォントリストを CSV / JSON でバックアップするツールです。
ローカル実行とクラウド定期実行の両方に対応し、アプリ本体は特定クラウドに依存しません。

## 特長

- **リストア可能な CSV** — `release_id` / `folder_id` / `instance_id` / `rating` / カスタムフィールド（Media Condition など）を出力
- **CSV / JSON を選択** — `--format csv|json|both`
- **クラウド非依存** — 保存先は `BACKUP_DEST`（`file://` / `gs://` / `s3://` / `az://`）+ fsspec
- **2 つの実行モード** — `MODE=http`（HTTP サーバ）/ `MODE=job`（単発実行）
- **冪等な保存キー** — 日付（`BACKUP_TZ` 基準）で上書きするため、スケジューラの再試行に耐える

## クイックスタート（ローカル）

```bash
# 依存なし（標準ライブラリのみ）で実行可能
export DISCOGS_PERSONAL_ACCESS_TOKEN="..."
export DISCOGS_USERNAME="your_username"

python3 discogs_backup.py --format csv
# -> ./discogs_backups/<timestamp>/collection.csv, wantlist.csv
```

### 環境変数

| 変数 | 説明 | 既定 |
|---|---|---|
| `DISCOGS_PERSONAL_ACCESS_TOKEN` | Discogs の Personal Access Token | — |
| `DISCOGS_USERNAME` | Discogs のユーザー名 | — |
| `DISCOGS_BACKUP_DIR` | ローカル保存先のルート | `./discogs_backups` |
| `BACKUP_FORMAT` | `csv` / `json` / `both`（コンテナ実行時） | `both` |
| `BACKUP_DEST` | 保存先 URI（未設定なら保存しない） | — |
| `BACKUP_TZ` | 保存キーに使うタイムゾーン | `Asia/Tokyo` |
| `CRON_TOKEN` | `/run` の共有トークン（任意） | — |
| `MODE` | `http` / `job` | `http` |
| `PORT` | HTTP 待ち受けポート | `8080` |

`.env` に書いた場合も読み込みます（`discogs_backup.py` と同じディレクトリ）。

## 開発環境（mise + uv）

Python は uv で管理します（`.python-version` で 3.12 に固定、Dockerfile と同一）。

```bash
mise install          # .mise.toml の uv を導入
uv python install     # .python-version の Python を導入
uv venv               # .venv を作成
uv pip install -r requirements-dev.txt
source .venv/bin/activate
```

テストは Discogs API のモック（`tests/mock_discogs.py`）を使うため、トークンやネットワークは不要です。

```bash
pytest
```

CI（`.github/workflows/ci.yml`）では pytest / `terraform validate` / Docker ビルドを実行します。

## コンテナ

```bash
# GCS 向け
docker build --build-arg STORAGE_BACKEND=gcs -t discogs-backup .

# 単発実行
docker run --rm -e DISCOGS_PERSONAL_ACCESS_TOKEN -e DISCOGS_USERNAME \
  -e BACKUP_FORMAT=csv -e BACKUP_DEST=gs://your-bucket/discogs \
  discogs-backup python worker.py job

# HTTP サーバ
docker run --rm -p 8080:8080 -e CRON_TOKEN=secret discogs-backup
curl -X POST -H "Authorization: Bearer secret" localhost:8080/run
```

`STORAGE_BACKEND` は `gcs` / `s3` / `azure` / `none`。

## クラウドでの定期実行

GCP（Cloud Run + Cloud Scheduler + GCS）用の Terraform を `infra/terraform/gcp/` に用意しています。
手順・無料枠の見積り・他クラウドへの対応表は [infra/README.md](infra/README.md) を参照してください。

```bash
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# 以降は infra/README.md の手順 1〜4
```

毎日 03:00（Asia/Tokyo）に実行され、`gs://<bucket>/discogs/YYYY-MM-DD/` に保存されます。

## 構成

```
discogs_backup.py   # API 取得・CSV/JSON 生成（クラウド SDK 非依存）
storage.py          # 保存先抽象化（fsspec）
worker.py           # MODE=http / MODE=job エントリポイント
Dockerfile          # クラウド非依存イメージ
cloudbuild.yaml     # Cloud Build 用ビルド定義
tests/              # pytest（Discogs API はモック）
.github/workflows/  # CI（pytest / terraform validate / docker build）
infra/              # Terraform（GCP）
```

## リストアについて

CSV の `release_id`（コレクションは `folder_id` も）を Discogs API に渡すことで復元できます。

- コレクション追加: `POST /users/{user}/collection/folders/{folder_id}/releases/{release_id}`
- カスタムフィールド: `POST .../releases/{release_id}/fields/{field_id}` に `{"value": "..."}`
- ウォントリスト: `PUT /users/{user}/wants/{release_id}` に `{"rating": r, "notes": "..."}`

## 注意

- Discogs API のレート制限は認証済みで 60 リクエスト/分です。全件取得は約 55 リクエスト・約 60 秒かかります。
- `discogs_backups/` は出力例です（`.gitignore` 済み）。不要なら削除してください。
