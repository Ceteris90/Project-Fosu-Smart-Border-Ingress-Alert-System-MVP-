#!/usr/bin/env bash
set -euo pipefail

# Create (idempotently) the Azure resources that back the Terraform azurerm
# backend declared in 2-infrastructure-as-code/Terraform/versions.tf:
#   * resource group
#   * StorageV2 account (HTTPS-only, TLS1.2, no public blob access, versioning)
#   * blob container
#   * "Storage Blob Data Contributor" for the current user (needed by
#     use_azuread_auth = true)
#
# Safe to re-run. Location defaults to the first CLI arg, then $LOCATION, then
# eastus2 (matching the Terraform `location` default).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSIONS_FILE="${PROJECT_ROOT}/2-infrastructure-as-code/Terraform/versions.tf"
LOCATION="${1:-${LOCATION:-eastus2}}"

command -v az >/dev/null 2>&1 || {
    printf 'ERROR: Required command not found: az\n' >&2
    exit 1
}
[[ -f "${VERSIONS_FILE}" ]] || {
    printf 'ERROR: %s not found\n' "${VERSIONS_FILE}" >&2
    exit 1
}

backend_value() {
    sed -n "s/.*$1[[:space:]]*=[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "${VERSIONS_FILE}" | head -n1
}

RESOURCE_GROUP="$(backend_value resource_group_name)"
STORAGE_ACCOUNT="$(backend_value storage_account_name)"
CONTAINER="$(backend_value container_name)"

[[ -n "${RESOURCE_GROUP}" && -n "${STORAGE_ACCOUNT}" && -n "${CONTAINER}" ]] || {
    printf 'ERROR: Could not parse the azurerm backend block from %s\n' "${VERSIONS_FILE}" >&2
    exit 1
}

az account show --output none >/dev/null 2>&1 || {
    printf "ERROR: Azure CLI is not authenticated; run 'az login'\n" >&2
    exit 1
}

USER_OBJECT_ID="$(az ad signed-in-user show --query id --output tsv)"

printf 'Backend target: %s / %s / %s (%s)\n' \
    "${RESOURCE_GROUP}" "${STORAGE_ACCOUNT}" "${CONTAINER}" "${LOCATION}"

if ! az group show --name "${RESOURCE_GROUP}" --output none 2>/dev/null; then
    printf 'Creating resource group %s\n' "${RESOURCE_GROUP}"
    az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output none
else
    printf 'Resource group %s already exists\n' "${RESOURCE_GROUP}"
fi

if ! az storage account show --name "${STORAGE_ACCOUNT}" --resource-group "${RESOURCE_GROUP}" --output none 2>/dev/null; then
    printf 'Creating storage account %s\n' "${STORAGE_ACCOUNT}"
    az storage account create \
        --name "${STORAGE_ACCOUNT}" \
        --resource-group "${RESOURCE_GROUP}" \
        --location "${LOCATION}" \
        --sku Standard_LRS \
        --kind StorageV2 \
        --https-only true \
        --min-tls-version TLS1_2 \
        --allow-blob-public-access false \
        --output none
else
    printf 'Storage account %s already exists\n' "${STORAGE_ACCOUNT}"
fi

# State-protection niceties; harmless to re-apply.
az storage account blob-service-properties update \
    --account-name "${STORAGE_ACCOUNT}" \
    --resource-group "${RESOURCE_GROUP}" \
    --enable-versioning true \
    --enable-delete-retention true \
    --delete-retention-days 30 \
    --output none

STORAGE_ACCOUNT_ID="$(az storage account show --name "${STORAGE_ACCOUNT}" --resource-group "${RESOURCE_GROUP}" --query id --output tsv)"

if ! az role assignment list \
    --assignee "${USER_OBJECT_ID}" \
    --scope "${STORAGE_ACCOUNT_ID}" \
    --include-inherited \
    --query "[?roleDefinitionName=='Storage Blob Data Contributor'] | [0]" \
    --output tsv | grep -q .; then
    printf 'Granting "Storage Blob Data Contributor" on the storage account\n'
    az role assignment create \
        --assignee-object-id "${USER_OBJECT_ID}" \
        --assignee-principal-type User \
        --role "Storage Blob Data Contributor" \
        --scope "${STORAGE_ACCOUNT_ID}" \
        --output none
    printf 'Waiting 30s for the role assignment to propagate\n'
    sleep 30
else
    printf 'User already has "Storage Blob Data Contributor" on the storage account\n'
fi

if ! az storage container show \
    --name "${CONTAINER}" \
    --account-name "${STORAGE_ACCOUNT}" \
    --auth-mode login \
    --output none 2>/dev/null; then
    printf 'Creating blob container %s\n' "${CONTAINER}"
    az storage container create \
        --name "${CONTAINER}" \
        --account-name "${STORAGE_ACCOUNT}" \
        --auth-mode login \
        --output none
else
    printf 'Blob container %s already exists\n' "${CONTAINER}"
fi

printf '\nBackend is ready. Next:\n'
printf '  terraform -chdir=2-infrastructure-as-code/Terraform init\n'
printf '  # or: scripts/deploy.sh infra\n'
