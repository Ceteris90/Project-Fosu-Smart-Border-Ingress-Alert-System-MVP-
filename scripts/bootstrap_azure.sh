#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TERRAFORM_DIR="${PROJECT_ROOT}/2-infrastructure-as-code/Terraform"
ENV_FILE="${PROJECT_ROOT}/.env"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"

HOSTNAME="${1:-fosu-dashboard-n9gsl.eastus2.cloudapp.azure.com}"
DEPLOYER_IP_CIDR="${2:-}"

for command_name in az openssl curl; do
    command -v "${command_name}" >/dev/null 2>&1 || {
        printf 'ERROR: Required command not found: %s\n' "${command_name}" >&2
        exit 1
    }
done

[[ -x "${PYTHON_BIN}" ]] || {
    printf 'ERROR: Create .venv and install python-dotenv first.\n' >&2
    exit 1
}
[[ -s "${ENV_FILE}" ]] || {
    printf 'ERROR: Run set_dashboard_password.py before this script.\n' >&2
    exit 1
}

if [[ -z "${DEPLOYER_IP_CIDR}" ]]; then
    DEPLOYER_IP_CIDR="$(curl --fail --silent --show-error --max-time 10 https://api.ipify.org)/32"
fi

SUBSCRIPTION_ID="$(az account show --query id --output tsv)"
mapfile -t dashboard_values < <("${PYTHON_BIN}" - "${ENV_FILE}" <<'PY'
import sys
from dotenv import dotenv_values

values = dotenv_values(sys.argv[1])
username = values.get("FOSU_DASHBOARD_USERNAME")
password_hash = values.get("FOSU_DASHBOARD_PASSWORD_HASH")
if not username or not password_hash:
    raise SystemExit("Dashboard credentials are incomplete in .env")
print(username)
print(password_hash)
PY
)
DASHBOARD_USERNAME="${dashboard_values[0]}"
DASHBOARD_PASSWORD_HASH="${dashboard_values[1]}"
DASHBOARD_CERTIFICATE_PASSWORD="$(openssl rand -hex 24)"
POSTGRES_ADMIN_PASSWORD="$(openssl rand -hex 32)"

umask 077
mkdir -p "${TERRAFORM_DIR}"

openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
    -keyout "${TERRAFORM_DIR}/dashboard.key" \
    -out "${TERRAFORM_DIR}/dashboard.crt" \
    -subj "/CN=${HOSTNAME}" \
    -addext "subjectAltName=DNS:${HOSTNAME}" >/dev/null 2>&1
openssl pkcs12 -export \
    -out "${TERRAFORM_DIR}/dashboard.pfx" \
    -inkey "${TERRAFORM_DIR}/dashboard.key" \
    -in "${TERRAFORM_DIR}/dashboard.crt" \
    -name dashboard-tls \
    -passout "pass:${DASHBOARD_CERTIFICATE_PASSWORD}" >/dev/null 2>&1
DASHBOARD_CERTIFICATE_BASE64="$(base64 -w0 "${TERRAFORM_DIR}/dashboard.pfx")"

openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "${TERRAFORM_DIR}/vpn-root.key" \
    -out "${TERRAFORM_DIR}/vpn-root.crt" \
    -subj "/CN=Project Fosu VPN Root" >/dev/null 2>&1
openssl req -newkey rsa:2048 -nodes \
    -keyout "${TERRAFORM_DIR}/vpn-client.key" \
    -out "${TERRAFORM_DIR}/vpn-client.csr" \
    -subj "/CN=Project Fosu VPN Client" >/dev/null 2>&1
openssl x509 -req -sha256 -days 825 \
    -in "${TERRAFORM_DIR}/vpn-client.csr" \
    -CA "${TERRAFORM_DIR}/vpn-root.crt" \
    -CAkey "${TERRAFORM_DIR}/vpn-root.key" \
    -CAcreateserial \
    -out "${TERRAFORM_DIR}/vpn-client.crt" \
    -extfile <(printf 'extendedKeyUsage=clientAuth\n') >/dev/null 2>&1

VPN_ROOT_CERTIFICATE_DATA="$(sed '/-----BEGIN CERTIFICATE-----/d; /-----END CERTIFICATE-----/d' "${TERRAFORM_DIR}/vpn-root.crt" | tr -d '\n')"
export SUBSCRIPTION_ID HOSTNAME DEPLOYER_IP_CIDR DASHBOARD_USERNAME
export DASHBOARD_PASSWORD_HASH DASHBOARD_CERTIFICATE_BASE64
export DASHBOARD_CERTIFICATE_PASSWORD
export POSTGRES_ADMIN_PASSWORD VPN_ROOT_CERTIFICATE_DATA TERRAFORM_DIR

"${PYTHON_BIN}" <<'PY'
import json
import os
from pathlib import Path

values = {
    "subscription_id": os.environ["SUBSCRIPTION_ID"],
    "dashboard_hostname": os.environ["HOSTNAME"],
    "deployer_ip_cidr": os.environ["DEPLOYER_IP_CIDR"],
    "dashboard_tls_certificate_base64": os.environ["DASHBOARD_CERTIFICATE_BASE64"],
    "dashboard_tls_certificate_password": os.environ["DASHBOARD_CERTIFICATE_PASSWORD"],
    "postgres_admin_password": os.environ["POSTGRES_ADMIN_PASSWORD"],
    "dashboard_username": os.environ["DASHBOARD_USERNAME"],
    "dashboard_password_hash": os.environ["DASHBOARD_PASSWORD_HASH"],
    "vpn_root_certificate_data": os.environ["VPN_ROOT_CERTIFICATE_DATA"],
}
content = "".join(f"{name} = {json.dumps(value)}\n" for name, value in values.items())
output = Path(os.environ["TERRAFORM_DIR"]) / "terraform.tfvars"
output.write_text(content, encoding="utf-8")
output.chmod(0o600)
PY

printf 'Created protected Azure deployment configuration for %s.\n' "${HOSTNAME}"
printf 'Generated files are ignored by Git under %s.\n' "${TERRAFORM_DIR}"