variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "db_password" {
  type      = string
  sensitive = true
  default   = "change-me-in-production"
}
