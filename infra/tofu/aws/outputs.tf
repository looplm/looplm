output "database_endpoint" {
  value = aws_db_instance.postgres.endpoint
}

output "redis_endpoint" {
  value = aws_elasticache_cluster.redis.cache_nodes[0].address
}

output "s3_bucket" {
  value = aws_s3_bucket.storage.id
}

output "eks_cluster_name" {
  value = aws_eks_cluster.main.name
}

output "eks_endpoint" {
  value = aws_eks_cluster.main.endpoint
}
