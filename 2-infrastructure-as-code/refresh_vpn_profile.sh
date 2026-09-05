#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
terraform_dir="$repo_root/2-infrastructure-as-code/Terraform"
profile_path="${VPN_PROFILE_PATH:-$repo_root/.local/vpn/OpenVPN/vpnconfig.ovpn}"
client_cert="${VPN_CLIENT_CERT:-$terraform_dir/vpn-client.crt}"
client_key="${VPN_CLIENT_KEY:-$terraform_dir/vpn-client.key}"
python_bin="$repo_root/.venv/bin/python"

[[ -x "$python_bin" ]] || python_bin="$(command -v python3)"
[[ -s "$client_cert" ]] || { echo "Missing VPN client certificate: $client_cert" >&2; exit 1; }
[[ -s "$client_key" ]] || { echo "Missing VPN client key: $client_key" >&2; exit 1; }

resource_group="$(terraform -chdir="$terraform_dir" output -raw resource_group_name)"
mapfile -t gateways < <(az network vnet-gateway list \
	--resource-group "$resource_group" \
	--query "[?gatewayType=='Vpn'].name" \
	--output tsv)

if [[ ${#gateways[@]} -ne 1 ]]; then
	echo "Expected one VPN gateway in $resource_group; found ${#gateways[@]}." >&2
	exit 1
fi

gateway_name="${gateways[0]}"
public_ip_id="$(az network vnet-gateway show \
	--resource-group "$resource_group" \
	--name "$gateway_name" \
	--query 'ipConfigurations[0].publicIPAddress.id' \
	--output tsv)"
public_ip="$(az network public-ip show --ids "$public_ip_id" --query ipAddress --output tsv)"
package_url="$(az network vnet-gateway vpn-client generate \
	--resource-group "$resource_group" \
	--name "$gateway_name" \
	--processor-architecture Amd64 \
	--output tsv)"

archive="$(mktemp)"
trap 'rm -f "$archive"' EXIT
curl --fail --silent --show-error --location "$package_url" --output "$archive"
mkdir -p "$(dirname "$profile_path")"

"$python_bin" - "$archive" "$profile_path" "$client_cert" "$client_key" "$public_ip" <<'PY'
import re
import sys
import zipfile
from pathlib import Path

archive, output, certificate, key, public_ip = sys.argv[1:]
with zipfile.ZipFile(archive) as package:
    profile_name = next(name for name in package.namelist() if name.lower().endswith(".ovpn"))
    profile = package.read(profile_name).decode("utf-8-sig")

profile = profile.replace("\r\n", "\n")
profile = re.sub(r"^remote\s+\S+\s+443$", f"remote {public_ip} 443", profile, flags=re.MULTILINE)
profile = profile.replace("#disable-dco", "disable-dco")
profile = re.sub(r"^log\s+.*$", f"log {Path(output).with_name('openvpn.log')}", profile, flags=re.MULTILINE)
profile = re.sub(r"<cert>.*?</cert>", f"cert {Path(certificate).resolve()}", profile, flags=re.DOTALL)
profile = re.sub(r"<key>.*?</key>", f"key {Path(key).resolve()}", profile, flags=re.DOTALL)

Path(output).write_text(profile, encoding="utf-8")
PY

chmod 600 "$profile_path"
echo "Refreshed $profile_path from Azure gateway $gateway_name ($public_ip)."