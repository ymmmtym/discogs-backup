locals {
  bucket_name = var.bucket_name != "" ? var.bucket_name : "${var.project_id}-discogs-backups"
  image       = var.image != "" ? var.image : "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.this.repository_id}/${var.service_name}:latest"

  services = [
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudscheduler.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------- storage
resource "google_storage_bucket" "backup" {
  name                        = local.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  lifecycle_rule {
    condition {
      age = var.retention_days
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------- secrets
resource "google_secret_manager_secret" "token" {
  secret_id = var.secret_token_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret" "username" {
  secret_id = var.secret_username_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}

# ---------------------------------------------------------------- container registry
resource "google_artifact_registry_repository" "this" {
  location      = var.region
  repository_id = var.service_name
  format        = "DOCKER"
  description   = "Discogs backup container images"

  depends_on = [google_project_service.enabled]
}

data "google_project" "this" {
  project_id = var.project_id
}

# Cloud Build がイメージを push できるようにする
resource "google_artifact_registry_repository_iam_member" "cloudbuild_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.this.location
  repository = google_artifact_registry_repository.this.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${data.google_project.this.number}@cloudbuild.gserviceaccount.com"
}

# ---------------------------------------------------------------- service accounts
resource "google_service_account" "runtime" {
  account_id   = "${var.service_name}-run"
  display_name = "Discogs backup runtime"
}

resource "google_service_account" "scheduler" {
  account_id   = "${var.service_name}-sched"
  display_name = "Discogs backup scheduler"
}

resource "google_storage_bucket_iam_member" "runtime_object_admin" {
  bucket = google_storage_bucket.backup.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_token" {
  secret_id = google_secret_manager_secret.token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_username" {
  secret_id = google_secret_manager_secret.username.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# ---------------------------------------------------------------- Cloud Run
resource "google_cloud_run_v2_service" "backup" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email
    timeout         = "600s"

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = local.image

      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }

      env {
        name  = "BACKUP_FORMAT"
        value = var.backup_format
      }
      env {
        name  = "BACKUP_DEST"
        value = "gs://${local.bucket_name}/${var.backup_prefix}"
      }
      env {
        name  = "BACKUP_TZ"
        value = var.timezone
      }
      env {
        name = "DISCOGS_USERNAME"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.username.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "DISCOGS_PERSONAL_ACCESS_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.token.secret_id
            version = "latest"
          }
        }
      }

      ports {
        container_port = 8080
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_storage_bucket_iam_member.runtime_object_admin,
    google_secret_manager_secret_iam_member.runtime_token,
    google_secret_manager_secret_iam_member.runtime_username,
  ]
}

# 認証必須（Scheduler は OIDC で呼ぶ）
resource "google_cloud_run_v2_service_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.backup.location
  name     = google_cloud_run_v2_service.backup.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# ---------------------------------------------------------------- scheduler
resource "google_cloud_scheduler_job" "daily" {
  name      = "${var.service_name}-daily"
  region    = var.region
  schedule  = var.schedule
  time_zone = var.timezone

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.backup.uri}/run"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = google_cloud_run_v2_service.backup.uri
    }
  }

  retry_config {
    retry_count = 1
  }

  depends_on = [google_cloud_run_v2_service_iam_member.scheduler_invoker]
}

# ---------------------------------------------------------------- budget (optional)
resource "google_billing_budget" "this" {
  count = var.billing_account == "" ? 0 : 1

  billing_account = var.billing_account
  display_name    = "${var.service_name} budget"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 1.0
  }
}
