# Observability backing store: an Azure Blob container for Loki log chunks.
# In-cluster traffic goes through the private endpoint below; Loki authenticates
# as a workload-identity federated credential (no keys). Public network access
# stays on but firewalled to the deployer IP so the provider can complete its
# data-plane readiness check and manage the container.

resource "azurerm_storage_account" "loki" {
  name                     = "st${var.name_prefix}loki${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = var.loki_storage_replication_type
  account_kind             = "StorageV2"
  min_tls_version          = "TLS1_2"
  # Keep shared-key access enabled: the azurerm provider reads blob/queue/share
  # service properties over the data plane with the account key on every plan.
  # Loki never uses the key (it authenticates with Workload Identity); real
  # access is still gated by the private endpoint + the firewall below.
  shared_access_key_enabled       = true
  https_traffic_only_enabled      = true
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = true
  tags                            = local.tags

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
    # Storage firewall rejects /32 (and /31); a single host must be a bare IP.
    ip_rules = var.deployer_ip_cidr != "" ? [trimsuffix(var.deployer_ip_cidr, "/32")] : []
  }
}

resource "azurerm_storage_container" "loki" {
  name                  = "loki"
  storage_account_id    = azurerm_storage_account.loki.id
  container_access_type = "private"
}

resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                  = "blob-vnet-link"
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.this.id
  resource_group_name   = azurerm_resource_group.this.name
  registration_enabled  = false
}

resource "azurerm_private_endpoint" "loki_blob" {
  name                = "pe-${local.name}-loki-blob"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id
  tags                = local.tags

  private_service_connection {
    name                           = "loki-blob"
    private_connection_resource_id = azurerm_storage_account.loki.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob.id]
  }
}

resource "azurerm_user_assigned_identity" "loki" {
  name                = "id-${local.name}-loki"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "loki_blob_contributor" {
  scope                = azurerm_storage_account.loki.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.loki.principal_id
}

resource "azurerm_federated_identity_credential" "loki" {
  name      = "loki"
  parent_id = azurerm_user_assigned_identity.loki.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject   = "system:serviceaccount:${var.monitoring_namespace}:loki"
}
