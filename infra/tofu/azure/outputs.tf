output "database_fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "redis_hostname" {
  value = azurerm_redis_cache.main.hostname
}

output "storage_account" {
  value = azurerm_storage_account.main.name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}
