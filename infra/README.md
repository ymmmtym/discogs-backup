# クラウドデプロイ手順（GCP 無料枠）

アプリ本体はクラウド非依存です。保存先は `BACKUP_DEST`、実行契機は各クラウドのスケジューラで切り替えます。

GCP（Cloud Run + Cloud Scheduler + GCS）の Terraform は **別リポジトリ [`ymmmtym/gcp`](https://github.com/ymmmtym/gcp) で管理**します。このリポジトリはコンテナイメージのビルドと GHCR への push までを担当します。

## 構成

```
GitHub Actions (main push)
        │ build --build-arg STORAGE_BACKEND=gcs
        ▼
GHCR  ghcr.io/ymmmtym/discogs-backup:latest
        │
        ▼
Cloud Scheduler (毎日 03:00 Asia/Tokyo, OIDC)
        │ POST /run
        ▼
Cloud Run (認証必須, max-instances=1, python:3.12 コンテナ)
        │ 環境変数: BACKUP_DEST=gs://<bucket>/discogs-backup
        ▼
GCS  gs://<bucket>/discogs-backup/YYYY-MM-DD/{collection,wantlist}.csv
     gs://<bucket>/discogs-backup/latest.json
```

## 無料枠の範囲

| サービス | Always Free | 想定使用量 |
|---|---|---|
| Cloud Run | 180,000 vCPU秒 / 360,000 GiB秒 月 | 約 1,800 vCPU秒（60秒×30日） |
| Cloud Scheduler | 3 ジョブ / 月 | 1 |
| Cloud Storage | 5 GB | CSV のみなら約 60 MB/月（90日で削除） |
| Secret Manager | 6 バージョン / 10,000 アクセス 月 | 2 シークレット / 約 60 アクセス |
| GitHub Container Registry | public パッケージは無料 | 1 イメージ |

請求アカウントの紐付けは必須ですが、上記の範囲では課金されません。

## デプロイ手順

### 1. イメージを GHCR に push

`main` に push すると `.github/workflows/release.yml` が自動でビルドし、`ghcr.io/ymmmtym/discogs-backup` に push します。

| イベント | タグ |
|---|---|
| main push | `latest`, `main`, `sha-<7桁>` |
| `v1.2.3` タグ | `1.2.3`, `1.2`, `sha-<7桁>` |
| 手動実行 | `latest`, `main`, `sha-<7桁>` |

初回 push 後、GitHub の Packages → `discogs-backup` → Package settings で **visibility を Public** に変更してください。private のままだと Cloud Run が認証なしで pull できません。

### 2. Terraform を適用（`ymmmtym/gcp` リポジトリ）

1. ブランチを切って PR を作成（Terraform Cloud が plan）
2. マージして apply
3. Secret Manager に値を投入（値は state に残さない）

   ```bash
   printf '%s' "$DISCOGS_PERSONAL_ACCESS_TOKEN" | \
     gcloud secrets versions add discogs-personal-access-token --data-file=-
   printf '%s' "$DISCOGS_USERNAME" | \
     gcloud secrets versions add discogs-username --data-file=-
   ```

   Secret の実体が無い状態で Cloud Run を作ると失敗するため、この順序で行います。

### 3. 手動実行（動作確認）

```bash
gcloud scheduler jobs run discogs-backup-daily --location us-central1
gcloud storage ls -r gs://<bucket>/discogs-backup/ | tail
```

`discogs-backup/YYYY-MM-DD/{collection,wantlist}.csv` と `discogs-backup/latest.json` が出力されれば成功です。

## イメージ更新時の注意

Cloud Run は `:latest` を push しても自動では再デプロイされません（デプロイ時に digest へ解決されるため）。更新は次のいずれかで行います。

```bash
# 不変タグ（sha-）で更新する場合
gcloud run services update discogs-backup \
  --region us-central1 \
  --image ghcr.io/ymmmtym/discogs-backup:sha-abc1234

# latest で更新する場合
gcloud run services update discogs-backup \
  --region us-central1 \
  --image ghcr.io/ymmmtym/discogs-backup:latest
```

Terraform 側はイメージを `ignore_changes` にして、CI / 手動更新と競合しないようにしています。

## ローカル実行

```bash
# 単発（ローカル保存）
python3 discogs_backup.py --format csv

# HTTP モード
pip install -r requirements.txt
MODE=http BACKUP_DEST=file:///tmp/discogs-backups python3 worker.py

# ジョブモード
MODE=job BACKUP_FORMAT=csv BACKUP_DEST=file:///tmp/discogs-backups python3 worker.py job

# GHCR のイメージを直接使う
docker run --rm -e DISCOGS_PERSONAL_ACCESS_TOKEN -e DISCOGS_USERNAME \
  -e BACKUP_FORMAT=csv -e BACKUP_DEST=file:///backups \
  -v "$PWD/backups:/backups" ghcr.io/ymmmtym/discogs-backup:latest python worker.py job
```

## 他クラウドへの展開（Terraform のみ差し替え）

| 項目 | GCP | AWS | Azure |
|---|---|---|---|
| 実行基盤 | Cloud Run | Lambda（コンテナイメージ）または ECS Fargate | Container Apps Job / Functions |
| スケジュール | Cloud Scheduler | EventBridge Scheduler | Container Apps Job の cron |
| 保存先 | `gs://` | `s3://` | `az://` |
| シークレット | Secret Manager | Secrets Manager / SSM | Key Vault |
| ビルド引数 | `STORAGE_BACKEND=gcs` | `s3` | `azure` |

アプリ側の変更は不要で、`BACKUP_DEST` とシークレットの渡し方だけが変わります。`MODE=job` にすると HTTP を公開せず 1 回実行して終了するため、Lambda（EventBridge 直叩き）/ ECS / ACA Job に向きます。

## 注意点

- **冪等性**: 保存キーは日付（`BACKUP_TZ` 基準）なので、Scheduler の再試行で上書きされます。
- **タイムアウト**: Cloud Run は `timeout = "600s"`。取得は約 60 秒です。
- **多重実行防止**: `max_instance_count = 1` とアプリ内ロックの二重で防いでいます。
- **認証**: Cloud Run は「認証が必要」でデプロイし、Scheduler のサービスアカウントに `roles/run.invoker` を付与します。アプリ側の `CRON_TOKEN` は他クラウド向けの任意設定です。
- **シークレット**: Terraform では secret の「入れ物」だけ作成します。値は `gcloud secrets versions add` で投入し、state に残しません。
