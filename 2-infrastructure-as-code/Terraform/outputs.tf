output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.this.name
}

output "dashboard_hostname" {
  value = var.dashboard_hostname
}

output "postgres_private_fqdn" {
  value = azurerm_postgresql_flexible_server.this.fqdn
}

output "application_gateway_public_ip" {
  value = azurerm_public_ip.app_gateway.ip_address
}

output "vpn_gateway_public_ip" {
  value = azurerm_public_ip.vpn_gateway.ip_address
}

output "monitoring_namespace" {
  value = var.monitoring_namespace
}

output "loki_storage_account_name" {
  value = azurerm_storage_account.loki.name
}

output "loki_storage_container_name" {
  value = azurerm_storage_container.loki.name
}

output "loki_identity_client_id" {
  value = azurerm_user_assigned_identity.loki.client_id
}
