variable "project_id" {
  description = "GCP プロジェクト ID"
  type        = string
}

variable "billing_account" {
  description = "予算アラートを作る場合の請求アカウント ID（例: 012345-6789AB-CDEF01）。空なら作成しない"
  type        = string
  default     = ""
}

variable "region" {
  description = "リージョン"
  type        = string
  default     = "asia-northeast1"
}

variable "service_name" {
  description = "Cloud Run サービス名・Artifact Registry リポジトリ名"
  type        = string
  default     = "discogs-backup"
}

variable "bucket_name" {
  description = "バックアップ保存先の GCS バケット名（空なら <project_id>-discogs-backups）"
  type        = string
  default     = ""
}

variable "backup_prefix" {
  description = "バケット内のプレフィックス"
  type        = string
  default     = "discogs"
}

variable "backup_format" {
  description = "出力形式: csv / json / both"
  type        = string
  default     = "csv"

  validation {
    condition     = contains(["csv", "json", "both"], var.backup_format)
    error_message = "backup_format は csv / json / both のいずれかです"
  }
}

variable "schedule" {
  description = "Cloud Scheduler の cron 式（既定: 毎日 03:00）"
  type        = string
  default     = "0 3 * * *"
}

variable "timezone" {
  description = "スケジュールと保存キーのタイムゾーン"
  type        = string
  default     = "Asia/Tokyo"
}

variable "retention_days" {
  description = "バックアップを保持する日数（GCS ライフサイクル）"
  type        = number
  default     = 90
}

variable "image" {
  description = "Cloud Run にデプロイするコンテナイメージ（空なら Artifact Registry の既定パス）"
  type        = string
  default     = ""
}

variable "secret_token_id" {
  description = "Discogs Personal Access Token を格納する Secret Manager の secret ID"
  type        = string
  default     = "discogs-personal-access-token"
}

variable "secret_username_id" {
  description = "Discogs ユーザー名を格納する Secret Manager の secret ID"
  type        = string
  default     = "discogs-username"
}

variable "budget_amount" {
  description = "予算アラートの金額（billing_account 指定時のみ）"
  type        = number
  default     = 100
}

variable "budget_currency" {
  description = "予算の通貨コード"
  type        = string
  default     = "JPY"
}
