data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  name = "${var.name_prefix}-${var.environment}"
  tags = {
    project     = "project-fosu"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "this" {
  name                = "vnet-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = ["10.20.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.20.0.0/20"]
}

resource "azurerm_subnet" "app_gateway" {
  name                 = "snet-appgw"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.20.16.0/24"]
}

resource "azurerm_subnet" "vpn_gateway" {
  name                 = "GatewaySubnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.20.17.0/24"]
}

resource "azurerm_subnet" "private_endpoints" {
  name                              = "snet-private-endpoints"
  resource_group_name               = azurerm_resource_group.this.name
  virtual_network_name              = azurerm_virtual_network.this.name
  address_prefixes                  = ["10.20.18.0/24"]
  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_public_ip" "app_gateway" {
  name                = "pip-appgw-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1", "2", "3"]
  domain_name_label   = split(".", var.dashboard_hostname)[0]
  tags                = local.tags
}

resource "azurerm_web_application_firewall_policy" "this" {
  name                = "waf-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  policy_settings {
    enabled                     = true
    mode                        = "Prevention"
    request_body_check          = true
    file_upload_limit_in_mb     = 100
    max_request_body_size_in_kb = 128
  }

  managed_rules {
    managed_rule_set {
      type    = "OWASP"
      version = "3.2"
    }
  }

  tags = local.tags
}

resource "azurerm_application_gateway" "this" {
  name                = "agw-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  zones               = ["1", "2", "3"]
  firewall_policy_id  = azurerm_web_application_firewall_policy.this.id

  sku {
    name = "WAF_v2"
    tier = "WAF_v2"
  }

  autoscale_configuration {
    min_capacity = 2
    max_capacity = 5
  }

  gateway_ip_configuration {
    name      = "gateway-ip-config"
    subnet_id = azurerm_subnet.app_gateway.id
  }

  frontend_port {
    name = "https"
    port = 443
  }

  frontend_ip_configuration {
    name                 = "public-frontend"
    public_ip_address_id = azurerm_public_ip.app_gateway.id
  }

  ssl_certificate {
    name     = "dashboard-tls"
    data     = var.dashboard_tls_certificate_base64
    password = var.dashboard_tls_certificate_password
  }

  backend_address_pool {
    name = "dashboard-backend"
  }

  backend_http_settings {
    name                  = "dashboard-http-settings"
    cookie_based_affinity = "Disabled"
    port                  = 8501
    protocol              = "Http"
    request_timeout       = 60
  }

  http_listener {
    name                           = "dashboard-listener"
    frontend_ip_configuration_name = "public-frontend"
    frontend_port_name             = "https"
    protocol                       = "Https"
    # Bind a managed certificate or Key Vault certificate in production.
    ssl_certificate_name = "dashboard-tls"
  }

  request_routing_rule {
    name                       = "dashboard-rule"
    rule_type                  = "Basic"
    http_listener_name         = "dashboard-listener"
    backend_address_pool_name  = "dashboard-backend"
    backend_http_settings_name = "dashboard-http-settings"
    priority                   = 100
  }

  lifecycle {
    ignore_changes = [
      backend_address_pool,
      backend_http_settings,
      frontend_port,
      http_listener,
      probe,
      redirect_configuration,
      request_routing_rule,
      rewrite_rule_set,
      url_path_map,
      tags["ingress-for-aks-cluster-id"],
      tags["managed-by-k8s-ingress"],
    ]
  }

  tags = local.tags
}

resource "azurerm_kubernetes_cluster" "this" {
  name                    = "aks-${local.name}"
  location                = azurerm_resource_group.this.location
  resource_group_name     = azurerm_resource_group.this.name
  dns_prefix              = "aks-${var.name_prefix}-${random_string.suffix.result}"
  kubernetes_version      = "1.35"
  sku_tier                = "Standard"
  private_cluster_enabled = true

  default_node_pool {
    name           = "system"
    vm_size        = "Standard_B2s"
    vnet_subnet_id = azurerm_subnet.aks.id
    # Zone 2 is restricted for Standard_B2s in eastus2 for this subscription.
    zones                        = ["1", "3"]
    auto_scaling_enabled         = true
    min_count                    = 3
    max_count                    = 6
    os_disk_type                 = "Managed"
    only_critical_addons_enabled = true

    upgrade_settings {
      drain_timeout_in_minutes      = 0
      max_surge                     = "10%"
      node_soak_duration_in_minutes = 0
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_policy      = "azure"
    load_balancer_sku   = "standard"
    service_cidr        = "10.30.0.0/16"
    dns_service_ip      = "10.30.0.10"
  }

  azure_policy_enabled              = true
  oidc_issuer_enabled               = true
  workload_identity_enabled         = true
  image_cleaner_enabled             = true
  image_cleaner_interval_hours      = 48
  local_account_disabled            = true
  role_based_access_control_enabled = true

  ingress_application_gateway {
    gateway_id = azurerm_application_gateway.this.id
  }

  azure_active_directory_role_based_access_control {
    tenant_id              = data.azurerm_client_config.current.tenant_id
    azure_rbac_enabled     = true
    admin_group_object_ids = []
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  }

  tags = local.tags
}

resource "azurerm_kubernetes_cluster_node_pool" "workload" {
  name                  = "workload"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = "Standard_B2s"
  vnet_subnet_id        = azurerm_subnet.aks.id
  zones                 = ["1", "3"]
  auto_scaling_enabled  = true
  min_count             = 3
  max_count             = 12
  mode                  = "User"
  node_labels = {
    "project-fosu/workload" = "application"
  }

  upgrade_settings {
    drain_timeout_in_minutes      = 0
    max_surge                     = "10%"
    node_soak_duration_in_minutes = 0
  }

  tags = local.tags
}

resource "azurerm_container_registry" "this" {
  name                    = replace("acr${var.name_prefix}${var.environment}${random_string.suffix.result}", "-", "")
  resource_group_name     = azurerm_resource_group.this.name
  location                = azurerm_resource_group.this.location
  sku                     = "Premium"
  admin_enabled           = false
  zone_redundancy_enabled = true
  tags                    = local.tags
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}

resource "azurerm_role_assignment" "aks_network_contributor" {
  scope                = azurerm_virtual_network.this.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.this.identity[0].principal_id
}

resource "azurerm_role_assignment" "current_aks_cluster_admin" {
  scope                = azurerm_kubernetes_cluster.this.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "agic_resource_group_reader" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Reader"
  principal_id         = azurerm_kubernetes_cluster.this.ingress_application_gateway[0].ingress_application_gateway_identity[0].object_id
}

resource "azurerm_role_assignment" "agic_application_gateway_contributor" {
  scope                = azurerm_application_gateway.this.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_kubernetes_cluster.this.ingress_application_gateway[0].ingress_application_gateway_identity[0].object_id
}

resource "azurerm_role_assignment" "agic_application_gateway_subnet_contributor" {
  scope                = azurerm_subnet.app_gateway.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.this.ingress_application_gateway[0].ingress_application_gateway_identity[0].object_id
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${local.name}-${random_string.suffix.result}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_key_vault" "this" {
  name                       = "kv-${var.name_prefix}-${random_string.suffix.result}"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = true
  soft_delete_retention_days = 90
  rbac_authorization_enabled = true
  # Public access is required for Terraform (run outside the VNet) to write secrets; restricted to the deployer IP below.
  public_network_access_enabled = true
  tags                          = local.tags

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
    ip_rules       = var.deployer_ip_cidr != "" ? [var.deployer_ip_cidr] : []
  }
}

resource "azurerm_role_assignment" "current_keyvault_admin" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "dashboard_username" {
  name         = "dashboard-username"
  value        = var.dashboard_username
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.current_keyvault_admin]

  lifecycle {
    ignore_changes = [value, tags]
  }
}

resource "azurerm_key_vault_secret" "dashboard_password_hash" {
  name         = "dashboard-password-hash"
  value        = var.dashboard_password_hash
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.current_keyvault_admin]

  lifecycle {
    ignore_changes = [value, tags]
  }
}

resource "azurerm_key_vault_secret" "postgres_admin_password" {
  name         = "postgres-admin-password"
  value        = var.postgres_admin_password
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.current_keyvault_admin]
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "postgres-vnet-link"
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.this.id
  resource_group_name   = azurerm_resource_group.this.name
  registration_enabled  = false
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.20.19.0/24"]
  delegation {
    name = "postgres-flexible-server"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "psql-${var.name_prefix}-${random_string.suffix.result}"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  administrator_login           = var.postgres_admin_username
  administrator_password        = var.postgres_admin_password
  storage_mb                    = 32768
  sku_name                      = "GP_Standard_D2ds_v5"
  zone                          = "1"
  high_availability {
    mode                      = "ZoneRedundant"
    standby_availability_zone = "2"
  }
  backup_retention_days        = 14
  geo_redundant_backup_enabled = true
  tags                         = local.tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

resource "azurerm_postgresql_flexible_server_database" "this" {
  name      = "fosu"
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_public_ip" "vpn_gateway" {
  name                = "pip-vpngw-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1", "2", "3"]
  tags                = local.tags
}

resource "azurerm_virtual_network_gateway" "this" {
  name                = "vpngw-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  type                = "Vpn"
  vpn_type            = "RouteBased"
  # Active-active requires 3 IP configs when combined with P2S VPN client config; not needed for P2S-only access.
  active_active = false
  bgp_enabled   = false
  sku           = "VpnGw2AZ"

  ip_configuration {
    name                          = "vpn-ip-config-1"
    public_ip_address_id          = azurerm_public_ip.vpn_gateway.id
    private_ip_address_allocation = "Dynamic"
    subnet_id                     = azurerm_subnet.vpn_gateway.id
  }

  vpn_client_configuration {
    address_space        = var.vpn_client_address_pool
    vpn_client_protocols = ["OpenVPN"]
    vpn_auth_types       = ["Certificate"]
    root_certificate {
      name             = "fosu-vpn-root"
      public_cert_data = var.vpn_root_certificate_data
    }
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}
