terraform {
  required_version = ">= 1.6.0"
}

variable "cloud_provider" {
  description = "Cloud provider: aws, gcp, or azure"
  type        = string
  default     = "aws"
}

module "aws" {
  source = "./aws"
  count  = var.cloud_provider == "aws" ? 1 : 0

  project_name = var.project_name
  environment  = var.environment
  region       = var.region
}

module "gcp" {
  source = "./gcp"
  count  = var.cloud_provider == "gcp" ? 1 : 0

  project_name = var.project_name
  environment  = var.environment
  region       = var.region
}

module "azure" {
  source = "./azure"
  count  = var.cloud_provider == "azure" ? 1 : 0

  project_name = var.project_name
  environment  = var.environment
  region       = var.region
}
