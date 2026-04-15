variable "project_name" {
  description = "Project name"
  type        = string
  default     = "looplm"
}

variable "environment" {
  description = "Environment (dev, staging, production)"
  type        = string
  default     = "dev"
}

variable "region" {
  description = "Cloud region"
  type        = string
  default     = "us-east-1"
}
