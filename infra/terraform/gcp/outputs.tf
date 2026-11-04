output "service_url" {
  description = "Cloud Run サービスの URL"
  value       = google_cloud_run_v2_service.backup.uri
}

output "bucket" {
  description = "バックアップ保存先バケット"
  value       = google_storage_bucket.backup.name
}

output "image" {
  description = "デプロイ対象のコンテナイメージ"
  value       = local.image
}

output "scheduler_job" {
  description = "Cloud Scheduler ジョブ名"
  value       = google_cloud_scheduler_job.daily.name
}

output "secrets" {
  description = "Secret Manager の secret ID"
  value = {
    token    = google_secret_manager_secret.token.secret_id
    username = google_secret_manager_secret.username.secret_id
  }
}
