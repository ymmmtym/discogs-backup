# クラウドデプロイ手順（GCP 無料枠）

アプリ本体はクラウド非依存です。保存先は `BACKUP_DEST`、実行契機は各クラウドのスケジューラで切り替えます。このディレクトリでは **GCP（Cloud Run + Cloud Scheduler + GCS）** の Terraform を提供します。

## 構成

```
Cloud Scheduler (毎日 03:00 Asia/Tokyo, OIDC)
        │ POST /run
        ▼
Cloud Run (認証必須, max-instances=1, python:3.12 コンテナ)
        │ 環境変数: BACKUP_DEST=gs://<bucket>/discogs
        ▼
GCS  gs://<bucket>/discogs/YYYY-MM-DD/{collection,wantlist}.csv
     gs://<bucket>/discogs/latest.json
```

## 無料枠の範囲

| サービス | Always Free | 想定使用量 |
|---|---|---|
| Cloud Run | 180,000 vCPU秒 / 360,000 GiB秒 月 | 約 1,800 vCPU秒（60秒×30日） |
| Cloud Scheduler | 3 ジョブ / 月 | 1 |
| Cloud Storage | 5 GB | CSV のみなら約 60 MB/月（90日で削除） |
| Secret Manager | 6 バージョン / 10,000 アクセス 月 | 2 シークレット / 約 60 アクセス |
| Artifact Registry | 0.5 GB | イメージ 1 個（GCS 用のみ導入） |
| Cloud Build | 120 分 / 日 | デプロイ時のみ |

請求アカウントの紐付けは必須ですが、上記の範囲では課金されません。`billing_account` を設定すると 50% / 100% で予算アラートが作成されます。

## デプロイ手順

```bash
# 0. 変数の用意
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars   # project_id / bucket_name を編集

# 1. API・レジストリ・シークレットの「入れ物」を作成
#    （Cloud Run はイメージとシークレットの実体が無いと起動できないため段階的に適用）
terraform init
terraform apply \
  -target=google_project_service.enabled \
  -target=google_artifact_registry_repository.this \
  -target=google_artifact_registry_repository_iam_member.cloudbuild_writer \
  -target=google_secret_manager_secret.token \
  -target=google_secret_manager_secret.username

# 2. シークレットを登録（値は state に残さない）
printf '%s' "$DISCOGS_PERSONAL_ACCESS_TOKEN" | \
  gcloud secrets versions add discogs-personal-access-token --data-file=-
printf '%s' "$DISCOGS_USERNAME" | \
  gcloud secrets versions add discogs-username --data-file=-

# 3. イメージをビルドして push（リポジトリ直下で実行）
cd ../..
IMAGE=$(terraform -chdir=infra/terraform/gcp output -raw image)
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_IMAGE="$IMAGE",_STORAGE_BACKEND=gcs .

# 4. 全体を適用（Cloud Run / Scheduler を作成）
terraform -chdir=infra/terraform/gcp apply
```

### 手動実行（動作確認）

```bash
URL=$(terraform -chdir=infra/terraform/gcp output -raw service_url)
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/run"
```

Cloud Run は「認証が必要」でデプロイしているため、呼び出し元に `roles/run.invoker` が必要です（自分のアカウントなら `gcloud run services add-iam-policy-binding` で付与）。

## ローカル実行

```bash
# 単発（ローカル保存）
python3 discogs_backup.py --format csv

# HTTP モード
pip install -r requirements.txt
MODE=http BACKUP_DEST=file:///tmp/discogs-backups python3 worker.py

# ジョブモード
MODE=job BACKUP_FORMAT=csv BACKUP_DEST=file:///tmp/discogs-backups python3 worker.py job
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
- **認証**: Cloud Run は「認証が必要」でデプロイし、Scheduler のサービスアカウントに `roles/run.invoker` を付与。アプリ側の `CRON_TOKEN` は他クラウド向けの任意設定です。
- **シークレット**: Terraform では secret の「入れ物」だけ作成します。値は `gcloud secrets versions add` で投入し、state に残しません。
