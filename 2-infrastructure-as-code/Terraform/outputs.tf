output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.this.name
}

output "acr_login_server" {
  value = azurerm_container_registry.this.login_server
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
