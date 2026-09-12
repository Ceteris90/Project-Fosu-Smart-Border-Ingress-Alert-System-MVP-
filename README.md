# Project Fosu Smart Border Ingress Alert System (MVP)
A prototype border-crossing logging, mapping, and threshold-alert system that covers **the whole border**, not just a handful of named checkpoints.

## Deployment options

Choose the deployment path that matches your environment:

1. **Local deployment** runs the API, dashboard, and sensor services on one
	machine with Docker Compose. Use this path for development and demonstrations.
2. **Azure deployment** provisions the production-style AKS, VPN, database,
	registry, and networking infrastructure. Use this path for a cloud deployment.

## Section 1: Local deployment

### Prerequisites

- Docker with the Compose plugin
- Git
- Python 3 with `venv` and `pip`

### Configure local credentials

From the repository root, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 1-app-source-code/scripts/set_dashboard_password.py --username fosu.admin
cp scripts/deployment.config.example scripts/deployment.config
```

The password command creates an ignored `.env` file containing the dashboard
username and a one-way password hash. It does not store the plain-text password.

### Start the application

```bash
scripts/deploy.sh local
```

After the containers start, open:

- Dashboard: `http://localhost:8501`
- API documentation: `http://localhost:8000/docs`

Check the deployment status or stop it with:

```bash
scripts/deploy.sh status
scripts/deploy.sh down
```

See [Local development and sensor testing](#local-development-and-sensor-testing)
for manual startup, mock sensor, YOLO, infrared, and multi-camera instructions.

## Section 2: Azure deployment

Azure AKS, VPN, and private-database deployment files are under
`2-infrastructure-as-code`.

### Prerequisites

- An Azure account with permission to create the required resources
- Azure CLI authenticated with `az login`
- Docker
- Terraform 1.6 or newer
- `kubectl` and `kubelogin`
- Ansible and the dependencies in `requirements.txt`
- Access to the Terraform state storage account described below
- A globally unique dashboard DNS name and a TLS certificate

### Deploy to Azure

First, create the non-secret deployment configuration and install the Python
and Ansible dependencies:

```bash
cp scripts/deployment.config.example scripts/deployment.config
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
ansible-galaxy collection install \
	-r 2-infrastructure-as-code/Ansible/requirements.yml \
	-p 2-infrastructure-as-code/Ansible/.collections
```

The deployment script uses the committed `inventory.ini.example` automatically.
To customize the inventory, copy it to the ignored local path before deployment:

```bash
cp 2-infrastructure-as-code/Ansible/inventory.ini.example \
	2-infrastructure-as-code/Ansible/inventory.ini
```

Before running preflight, provide these required Terraform values in the
ignored `2-infrastructure-as-code/Terraform/terraform.tfvars` file or through
matching `TF_VAR_*` environment variables:

- `subscription_id`
- `dashboard_hostname`
- `dashboard_tls_certificate_password`
- `postgres_admin_password`
- `dashboard_password_hash`
- `vpn_root_certificate_data`

Also provide `dashboard_tls_certificate_base64`, or place a non-empty
`dashboard.pfx` in `2-infrastructure-as-code/Terraform/` so the deployment
script can encode it automatically. Set `deployer_ip_cidr` to the public IP or
CIDR that must access Key Vault during initial deployment.

For a development deployment, generate a one-year self-signed dashboard
certificate, VPN certificates, random infrastructure passwords, and the ignored
Terraform variable file after configuring the dashboard password:

```bash
scripts/bootstrap_azure.sh fosu-dashboard-n9gsl.eastus2.cloudapp.azure.com
```

The generated dashboard certificate is suitable for testing but causes browser
trust warnings. Replace it with a certificate issued by a trusted authority for
production.

The detailed certificate, Terraform, VPN, and Ansible preparation steps are in
[Azure infrastructure details](#azure-infrastructure-details).

For the first deployment, provision the infrastructure before connecting to the
new private network:

```bash
scripts/deploy.sh preflight
scripts/deploy.sh infra
./2-infrastructure-as-code/refresh_vpn_profile.sh
sudo openvpn --config .local/vpn/OpenVPN/vpnconfig.ovpn
```

Wait for `Initialization Sequence Completed` and leave OpenVPN running. In a
second terminal, deploy the application and check its status:

```bash
source .venv/bin/activate
scripts/deploy.sh app
scripts/deploy.sh status
```

For later updates, while the VPN is already connected, `scripts/deploy.sh deploy`
runs the build, Terraform, scanning, and Ansible phases together. The command
refuses to start without an active VPN tunnel so it cannot provision resources
and then fail when private AKS access is required. Ansible prompts for the Vault
password only when protected local Ansible variables are used.

### Remove the Azure deployment on cloud

Azure teardown is deliberately guarded because it destroys cloud resources:

```bash
scripts/deploy.sh destroy --confirm-destroy
```

Review the Terraform plan and confirm that retained resources, including the
VPN gateway, are handled as intended before approving destruction.

## Deployment command reference

Use `scripts/deploy.sh` as the single entry point for local and Azure
deployments. Optional non-secret defaults can be copied from
`scripts/deployment.config.example` to the ignored
`scripts/deployment.config` file.

```bash
cp scripts/deployment.config.example scripts/deployment.config
scripts/deploy.sh preflight
scripts/deploy.sh local
scripts/deploy.sh deploy
scripts/deploy.sh status
```

The full cloud deployment builds and pushes the image, applies Terraform,
pulls and scans the registry image, and then uses Ansible to configure the
infrastructure and deploy to private AKS. Connect the Azure VPN before the
Ansible phase. Ansible prompts for the Vault password by default; automation
can set `ANSIBLE_VAULT_PASSWORD_FILE` to a protected file.
Individual phases are available as `build`, `scan`, `infra`, and `app`; use
`scripts/deploy.sh --help` for all options. Azure teardown is deliberately
guarded and requires `--confirm-destroy`.

## Azure infrastructure details

Terraform provisions the Project Fosu Azure foundation:

- zone-spread AKS system and user node pools in a VNet;
- a public Application Gateway (WAF_v2) for the dashboard only;
- an internal API service and YOLO workers inside AKS;
- private Azure Database for PostgreSQL Flexible Server;
- Azure Key Vault for dashboard and database secrets;
- Log Analytics with diagnostic settings for the gateway, Key Vault, and
	database; and
- Point-to-site Azure VPN Gateway for camera and operator access.

The application image is pulled from the public registry named by
`IMAGE_REPOSITORY` (Docker Hub by default), so no Azure Container Registry is
provisioned; see the note in `Terraform/main.tf` to add a private ACR.

The default region is `eastus2`, with availability zones `1`, `2`, and `3`.
Operators need Azure CLI authentication, Terraform 1.6 or newer, permission to
create these Azure resources, and a globally unique dashboard DNS name.

Cost-sensitive non-production environments can override `postgres_sku_name`,
`postgres_high_availability_enabled`, `postgres_geo_redundant_backup_enabled`,
and related variables (see `Terraform/variables.tf`); the defaults keep the
production posture.

### Terraform state and deployment

Production state uses the Azure backend declared in
`2-infrastructure-as-code/Terraform/versions.tf`:

- resource group: `rg-fosu-tfstate`;
- storage account: `stfosutfstatejsflw`;
- container: `tfstate`; and
- state key: `project-fosu-prod.tfstate`.

Create these resources once per subscription with the idempotent helper (it
also grants the current user `Storage Blob Data Contributor`, required by
`use_azuread_auth = true`):

```bash
scripts/bootstrap_backend.sh
```

`scripts/deploy.sh preflight` fails early if the backend container is missing or
unreadable. Do not change the backend or state key to bypass access errors
because that would make existing resources appear unmanaged.

```bash
cd 2-infrastructure-as-code/Terraform
terraform init
test -s dashboard.pfx
export TF_VAR_dashboard_tls_certificate_base64="$(base64 -w0 dashboard.pfx)"
terraform plan -out tfplan
terraform apply tfplan
```

The VPN gateway has `prevent_destroy` enabled because replacement invalidates
downloaded client profiles. For an intentional replacement, temporarily remove
the guard, apply the reviewed plan, restore the guard, and refresh the VPN
profile before reconnecting.

Local Terraform variables, state, plans, certificates, and private keys are
ignored by the root `.gitignore`. Prefer CI/CD secret storage or environment
variables such as `TF_VAR_postgres_admin_password` and
`TF_VAR_dashboard_password_hash`. The PFX password must match `dashboard.pfx`.

The dashboard currently uses:

```text
https://fosu-dashboard-n9gsl.eastus2.cloudapp.azure.com
```

It has a self-signed certificate until a trusted production certificate is
installed.

### Private AKS access and Ansible

AKS has a private API endpoint. Refresh and connect the Azure VPN before using
Ansible:

```bash
./2-infrastructure-as-code/refresh_vpn_profile.sh
sudo openvpn --config .local/vpn/OpenVPN/vpnconfig.ovpn
```

Wait for `Initialization Sequence Completed` and leave OpenVPN running. In a
separate terminal, install the required Ansible collection and Python client:

```bash
source .venv/bin/activate
python3 -m pip install -r requirements.txt
ansible-galaxy collection install \
	-r 2-infrastructure-as-code/Ansible/requirements.yml \
	-p 2-infrastructure-as-code/Ansible/.collections
```

For a custom inventory, copy the committed example. If local Ansible variables
are required, copy and populate the example variable file, then encrypt it:

```bash
cd 2-infrastructure-as-code/Ansible
cp inventory.ini.example inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
ansible-vault encrypt group_vars/all.yml
cd ../..
```

Deploy with the central script, or run Ansible directly:

```bash
export KUBECONFIG=/tmp/project-fosu-kubeconfig
ansible-playbook \
	-i 2-infrastructure-as-code/Ansible/inventory.ini \
	2-infrastructure-as-code/Ansible/site.yml \
	--ask-vault-pass
```

The playbook obtains private AKS credentials, configures routing while retaining
TLS hostname verification, creates the `project-fosu` namespace and application
Secret, applies the API, dashboard, YOLO sensor, network policy, and ingress,
then waits for the deployments. The dashboard is public through Application
Gateway; the API remains a private `ClusterIP` at
`http://fosu-api:8000/ingest`.

Production deployments must use the private PostgreSQL hostname with
`sslmode=require`, keep public database access disabled, inject secrets through
Key Vault or a protected pipeline, and use a trusted TLS certificate.

### Build and publish the deployment image

```bash
docker login
docker build -f 1-app-source-code/Dockerfile \
	-t ceteris90/project-fosu:latest .
docker push ceteris90/project-fosu:latest
docker manifest inspect ceteris90/project-fosu:latest >/dev/null
```

## Local development and sensor testing

### Run services without Docker

```bash
source .venv/bin/activate
uvicorn --app-dir 1-app-source-code app.main:app --reload --port 8000
streamlit run 1-app-source-code/dashboard/dashboard.py
```

Open `http://localhost:8501`. The dashboard is protected by a session login and does not request operational API data until authentication succeeds.

### Replace mock sensor with YOLO detection

You can feed live detections from a camera/video stream into the same existing ingestion logic (no backend changes required):

```bash
source .venv/bin/activate
pip install -r requirements.txt
python 1-app-source-code/scripts/yolo_sensor.py \
	--source 0 \
	--camera-lat 6.1219 \
	--camera-lon 1.1974 \
	--post-interval 5 \
	--display
```

Notes:

- `--source` can be webcam index (`0`), video file path, or RTSP URL.
- The script sends the same payload shape used by `mock_sensor.py` to `/ingest`.
- Keep `uvicorn` running first so YOLO events can be recorded and visualized on the dashboard.

#### Switch sensors during a demonstration

Keep the API and dashboard running in separate terminals:

```bash
source .venv/bin/activate
uvicorn --app-dir 1-app-source-code app.main:app --host 127.0.0.1 --port 8000
```

```bash
source .venv/bin/activate
streamlit run 1-app-source-code/dashboard/dashboard.py
```

Run only one event producer at a time. Start with simulated events:

```bash
source .venv/bin/activate
python3 1-app-source-code/scripts/mock_sensor.py --interval 5
```

That command expects a local API on port `8000`. To send events to the private
AKS API instead, keep the Azure VPN connected and start a port-forward in a
separate terminal:

```bash
1-app-source-code/scripts/port_forward_api.sh
```

The wrapper restarts `kubectl port-forward` if the VPN reconnects or the selected
API pod becomes unavailable. Stop it with `Ctrl+C`.

Then run the mock sensor with the explicit ingestion endpoint:

```bash
source .venv/bin/activate
python3 1-app-source-code/scripts/mock_sensor.py \
	--api-url http://127.0.0.1:8000/ingest \
	--interval 5
```

Stop the mock sensor with `Ctrl+C`. For a short batch instead, use:

```bash
python3 1-app-source-code/scripts/mock_sensor.py --once --n 20
```

Then start the camera sensor. This workspace includes a locally generated,
dark monochrome test clip at `.local/videos/vtest-night-ir.avi`. It simulates
severe illumination loss, IR-style monochrome output, sensor noise, and lens
falloff while retaining pedestrians for repeatable pipeline testing:

```bash
test -r .local/videos/vtest-night-ir.avi
source .venv/bin/activate
python3 1-app-source-code/scripts/yolo_sensor.py \
	--api-url http://127.0.0.1:8000/ingest \
	--model yolov8n.pt \
	--source .local/videos/vtest-night-ir.avi \
	--classes person \
	--low-light \
	--infrared \
	--inference-confidence 0.20 \
	--min-confidence 0.20 \
	--imgsz 640 \
	--display
```

This clip validates the software path; it is not evidence of field performance
in a forest. In complete darkness, use a camera with its own IR illuminator or
a thermal camera. An ordinary webcam plus `--low-light` cannot recover details
that the camera did not capture.

For a live USB IR camera, connect it to the VMware guest and replace the source
with `--source 0` after `test -r /dev/video0` succeeds. For an authorized RTSP
IR camera, provide its stream URL without writing credentials into this README:

```bash
read -r -s -p "Authorized RTSP URL: " FOSU_RTSP_URL
printf '\n'
if [[ -z "$FOSU_RTSP_URL" ]]; then
	printf 'No RTSP URL entered. Example: rtsp://user:password@camera-ip:554/stream\n'
else
	python3 1-app-source-code/scripts/yolo_sensor.py \
		--api-url http://127.0.0.1:8000/ingest \
		--model yolov8n.pt \
		--source "$FOSU_RTSP_URL" \
		--classes person \
		--low-light \
		--infrared \
		--inference-confidence 0.20 \
		--min-confidence 0.20 \
		--imgsz 640 \
		--display
fi
unset FOSU_RTSP_URL
```

Keep the AKS port-forward shown above running while testing. Use only streams
you own or are explicitly authorized to access.

Stop YOLO with `q` in the preview window or `Ctrl+C` in its terminal before
switching back to `mock_sensor.py`. Both sensors send events to the same
`/ingest` endpoint, so new detections appear in the dashboard automatically.

#### Lightweight infrared night detection

Use an IR-capable USB or RTSP camera with the lightweight YOLO model. The
`--infrared` option enhances monochrome IR frames and converts them to the
three-channel format expected by YOLO:

```bash
python 1-app-source-code/scripts/yolo_sensor.py \
	--model yolov8n.pt \
	--source 0 \
	--classes person \
	--infrared \
	--inference-confidence 0.20 \
	--min-confidence 0.20 \
	--imgsz 640 \
	--display
```

For small or distant people, use `yolov8s.pt` and `--imgsz 960`, but expect
slower CPU inference. A thermal camera requires a model trained or fine-tuned
on thermal imagery; ordinary YOLO weights may not detect thermal silhouettes
reliably.

#### Multi-camera mode (one process)

Use the JSON camera list (one worker thread per enabled camera):

```bash
python 1-app-source-code/scripts/yolo_sensor.py \
	--config 1-app-source-code/scripts/cameras.example.json
```

Each camera entry can define its own `source`, geolocation, confidence threshold,
post interval, and optional calibration file.

#### Zone calibration for better geolocation

To map pixel regions to more realistic geo locations, provide a calibration file
for each camera (example: `1-app-source-code/scripts/calibration.example.json`).

Calibration format:

```json
{
	"frame_width": 1920,
	"frame_height": 1080,
	"zones": [
		{
			"name": "zone-name",
			"pixel": [x1, y1, x2, y2],
			"geo": [min_lat, min_lon, max_lat, max_lon]
		}
	]
}
```

If a detection center falls inside a zone, coordinates are projected using that
zone mapping. If no zone matches, the script falls back to lat/lon span mapping.

### Docker Compose reference

Build and start the API and dashboard with Compose:

```bash
docker compose up --build -d
```

Compose loads dashboard credentials from `.env`, publishes ports `8000` and `8501`, and persists SQLite data in the `fosu-data` named volume.

Compose also starts the `yolo-sensor` service, which reads camera streams from:

- `1-app-source-code/scripts/cameras.example.json`

Update that file with your real RTSP/video sources and camera coordinates.

View logs or stop the application with:

```bash
docker compose logs -f
docker compose down
```

Open the dashboard at `http://localhost:8501` or the API documentation at `http://localhost:8000/docs`.

## Observability (Loki / Prometheus / Grafana)

An optional in-cluster stack for metrics, logs, and alerting, installed into a
dedicated `monitoring` namespace by Helm charts driven from Ansible.

- **Prometheus** (kube-prometheus-stack) scrapes kube-state-metrics,
  node-exporter, and cAdvisor: CPU / memory / network per pod, restarts, replica
  health, PVC usage. TSDB on a `managed-csi` PVC, 10-day retention.
- **Loki** stores log chunks in a private Azure Blob container
  (`monitoring.tf`), authenticating as a Workload Identity (no keys). It runs in
  SingleBinary mode.
- **Promtail** (DaemonSet) tails `/var/log/pods` on every node and ships all pod
  logs to Loki, labelled by `namespace` / `pod` / `container` — so `fosu-api`,
  `fosu-dashboard`, and `fosu-yolo-sensor` logs are searchable in Grafana with no
  app changes.
- **Grafana** ships with a Loki data source, community dashboards, a
  Fosu-specific board (`2-infrastructure-as-code/monitoring/dashboards/`), and
  Alertmanager alerts (kube-prometheus-stack defaults plus
  `monitoring/fosu-alerts.yaml`).

Prerequisites: `terraform apply` including `monitoring.tf` (`scripts/deploy.sh
infra`), the `helm` binary, and an active VPN tunnel. The playbook regenerates
`/tmp/project-fosu-kubeconfig` from Terraform state on every run, so it no longer
depends on a prior `scripts/deploy.sh app`.

```bash
scripts/deploy.sh infra          # provisions the Loki storage + federated identity
scripts/deploy.sh monitoring     # helm installs kps + loki + promtail

# everything below is ClusterIP -- point kubectl at the project kubeconfig,
# otherwise it falls back to ~/.kube/config (e.g. a stale minikube context)
export KUBECONFIG=/tmp/project-fosu-kubeconfig

# each port-forward is foreground; run in its own terminal (or append &)
kubectl -n monitoring port-forward svc/grafana          3000:80    # http://localhost:3000
kubectl -n monitoring port-forward svc/kps-prometheus   9090:9090  # http://localhost:9090
kubectl -n monitoring port-forward svc/kps-alertmanager 9093:9093  # http://localhost:9093
kubectl -n monitoring port-forward svc/loki             3100:3100  # HTTP API only, no UI

# Grafana admin credentials (username defaults to "admin")
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-user}'     | base64 -d ; echo
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d ; echo
```

Loki has no web UI -- browse logs through Grafana (Explore, the pre-provisioned
"Loki" datasource) or hit its API directly, e.g. `curl -s
http://localhost:3100/ready` and `curl -sG
http://localhost:3100/loki/api/v1/query_range --data-urlencode
'query={namespace="project-fosu"}'`.

Set `GRAFANA_ADMIN_PASSWORD` in the environment before the first run to choose
the admin password; otherwise one is generated and stored in the `grafana-admin`
secret. Chart versions are pinned in
`2-infrastructure-as-code/monitoring/chart-versions.yaml`. Container Insights
(`oms_agent`) still runs in parallel; disable it in `main.tf` if you standardise
on Grafana.

Sizing note: the stack adds ~2 GiB of requests across the `Standard_B2s` user
pool, so the cluster autoscaler will likely add a node. Move monitoring to a
dedicated node pool (or larger VMs) for anything beyond an MVP.

In CI, run **Actions → CI/CD pipeline → Run workflow → deploy: `monitoring`**.

## CI/CD pipeline

`.github/workflows/security-quality.yml` runs one workflow whose jobs mirror the
`scripts/deploy.sh` roadmap, chained with `needs:`:

```
preflight -> build -> scan -> push -> infra -> {app, monitoring} -> status
```

- **preflight** – `terraform fmt`/`validate`, `shellcheck`, `hadolint`, and
	`ansible-playbook --syntax-check`.
- **build** – builds the image and warms the buildx cache.
- **scan** – Trivy image scan (fails on fixable HIGH/CRITICAL), Trivy source
	scan (SARIF to the Security tab), then SonarQube when its secrets are set.
- **push** – pushes `:<sha>` and `:latest` to the registry. Runs only on
	`main`/`master` or a manual run, and only when `REGISTRY_USERNAME` /
	`REGISTRY_PASSWORD` are set.
- **infra** – `terraform init/validate/plan` against the real backend on every
	run that has the Azure OIDC secrets; `terraform apply` only from a manual
	**Run workflow** with the `deploy` input set to `infra`, `app`, or
	`monitoring`, gated by the `production` Environment.
- **app** – `ansible-playbook site.yml`, only when `deploy=app`. On a
	GitHub-hosted runner it connects the P2S VPN from `VPN_CLIENT_CERT` /
	`VPN_CLIENT_KEY`; set the `FOSU_DEPLOY_RUNNER` variable to a self-hosted
	runner inside the VNet instead (recommended).
- **monitoring** – `ansible-playbook monitoring.yml` (helm installs the LGTM
	stack), only when `deploy=monitoring`. Same runner/VPN story as **app**; also
	reads `GRAFANA_ADMIN_PASSWORD` if set.
- **status** – prints `terraform output` to the run summary.

Everything past **scan** is gated on the matching secrets/vars, so an
unconfigured repo still gets preflight + build + scan and nothing hard-fails.
Configure:

| Purpose | Repository secrets | Repository variables |
| --- | --- | --- |
| SonarQube | `SONAR_TOKEN`, `SONAR_HOST_URL` | – |
| Registry push | `REGISTRY_USERNAME`, `REGISTRY_PASSWORD` | `IMAGE_REPOSITORY` (default `ceteris90/project-fosu`) |
| Azure (OIDC) | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | – |
| Terraform vars | `TF_VAR_dashboard_hostname`, `TF_VAR_dashboard_password_hash`, `TF_VAR_postgres_admin_password`, `TF_VAR_dashboard_tls_certificate_base64`, `TF_VAR_dashboard_tls_certificate_password`, `TF_VAR_vpn_root_certificate_data` | – |
| App deploy | `VPN_CLIENT_CERT`, `VPN_CLIENT_KEY` (hosted runner only) | `FOSU_DEPLOY_RUNNER` (self-hosted runner label) |
| Monitoring | `GRAFANA_ADMIN_PASSWORD` (optional) | – |

The federated Azure identity needs `Storage Blob Data Contributor` on the
Terraform state account plus permission to manage the target resources. Use a
`project-fosu-smart-border` SonarQube project key. Configure the `production`
Environment with required reviewers to approve `apply` / `app`. Update branch
protection required checks to the new job names (`preflight`, `scan`, …).

The GitHub-hosted runner must be able to reach `SONAR_HOST_URL`. Use a
self-hosted runner or expose SonarQube through an authenticated HTTPS endpoint
when the server is on a private network. Trivy results are uploaded to the
repository's Security tab; this requires GitHub code scanning to be enabled.

The repository has one root `.gitignore` that protects local credentials,
Terraform state, private keys, certificates, VPN profiles, kubeconfigs, Ansible
Vault data, and deployment configuration throughout the repository. Ignore
rules do not protect files that were already committed or secrets stored under
unexpected filenames, so review `git status` and keep the Trivy secret scan
passing before every push. If a secret is ever committed, revoke or rotate it
and remove it from Git history; adding it to `.gitignore` is not sufficient.

## Dashboard credentials

Credentials are read from the ignored `.env` file as `FOSU_DASHBOARD_USERNAME` and a one-way `FOSU_DASHBOARD_PASSWORD_HASH`. Rotate them with:

```bash
python 1-app-source-code/scripts/set_dashboard_password.py --username fosu.admin
```

The command prompts for the password without displaying it, writes a salted scrypt hash, and never stores the plain-text password. Reload the login page after changing credentials. In deployment, provide the same environment variables through the hosting platform's secret manager instead of committing `.env`.
