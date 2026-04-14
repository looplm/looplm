# LoopLM Infrastructure (OpenTofu)

## Multi-Cloud Approach

LoopLM is cloud-agnostic by design. Infrastructure is defined using [OpenTofu](https://opentofu.org/) with separate modules per cloud provider:

- **`aws/`** — AWS (EKS, RDS PostgreSQL, ElastiCache Redis, S3)
- **`gcp/`** — GCP (GKE, Cloud SQL, Memorystore, Cloud Storage)
- **`azure/`** — Azure (AKS, Azure Database for PostgreSQL, Azure Cache, Blob Storage)

## Usage

```bash
cd infra/tofu
tofu init
tofu plan -var="environment=dev"
tofu apply -var="environment=dev"
```

## Principles

- No vendor-locked cloud services in the critical path
- All resources are Kubernetes-native or managed equivalents
- S3-compatible object storage across all providers
- Managed PostgreSQL everywhere (no proprietary DB services)
