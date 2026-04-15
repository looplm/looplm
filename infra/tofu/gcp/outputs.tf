output "database_connection" {
  value = google_sql_database_instance.postgres.connection_name
}

output "redis_host" {
  value = google_redis_instance.main.host
}

output "gcs_bucket" {
  value = google_storage_bucket.storage.name
}

output "gke_cluster_name" {
  value = google_container_cluster.main.name
}
