variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "region" {
  type    = string
  default = "eastus"
}

variable "db_password" {
  type      = string
  sensitive = true
  default   = "change-me-in-production"
}
