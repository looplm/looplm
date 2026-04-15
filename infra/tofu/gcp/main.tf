terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

variable "gcp_project" {
  type    = string
  default = "looplm"
}

provider "google" {
  project = var.gcp_project
  region  = var.region
}

# VPC
resource "google_compute_network" "main" {
  name                    = "${var.project_name}-${var.environment}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name          = "${var.project_name}-${var.environment}-subnet"
  ip_cidr_range = "10.0.0.0/20"
  region        = var.region
  network       = google_compute_network.main.id
}

# Cloud SQL PostgreSQL
resource "google_sql_database_instance" "postgres" {
  name             = "${var.project_name}-${var.environment}-db"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = "db-f1-micro"

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "looplm" {
  name     = "looplm"
  instance = google_sql_database_instance.postgres.name
}

# Memorystore Redis
resource "google_redis_instance" "main" {
  name           = "${var.project_name}-${var.environment}-redis"
  tier           = "BASIC"
  memory_size_gb = 1
  region         = var.region

  authorized_network = google_compute_network.main.id
}

# GCS Bucket
resource "google_storage_bucket" "storage" {
  name     = "${var.project_name}-${var.environment}-storage"
  location = var.region

  uniform_bucket_level_access = true
}

# GKE Cluster
resource "google_container_cluster" "main" {
  name     = "${var.project_name}-${var.environment}"
  location = var.region

  network    = google_compute_network.main.name
  subnetwork = google_compute_subnetwork.main.name

  initial_node_count       = 1
  remove_default_node_pool = true
}

resource "google_container_node_pool" "primary" {
  name       = "primary"
  location   = var.region
  cluster    = google_container_cluster.main.name
  node_count = 2

  node_config {
    machine_type = "e2-medium"
    disk_size_gb = 50
  }
}
