# Project-Fosu-Smart-Border-Ingress-Alert-System-MVP-
A prototype border-crossing logging, mapping, and threshold-alert system that covers **the whole border**, not just a handful of named checkpoints.

Azure AKS/VPN/private-database deployment files are under
`2-infrastructure-as-code`; their operating instructions are included here.

## Central deployment script

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

The full cloud deployment builds and scans the image, pushes it, applies
Terraform, and runs the Ansible deployment against private AKS. Connect the
Azure VPN before the Ansible phase. Ansible prompts for the Vault password by
default; automation can set `ANSIBLE_VAULT_PASSWORD_FILE` to a protected file.
Individual phases are available as `build`, `scan`, `infra`, and `app`; use
`scripts/deploy.sh --help` for all options. Azure teardown is deliberately
guarded and requires `--confirm-destroy`.

## Azure infrastructure

Terraform provisions the Project Fosu Azure foundation:

- zone-spread AKS system and user node pools in a VNet;
- a public Application Gateway for the dashboard only;
- an internal API service and YOLO workers inside AKS;
- private Azure Database for PostgreSQL Flexible Server;
- Azure Key Vault for dashboard and database secrets;
- Azure Container Registry; and
- Point-to-site Azure VPN Gateway for camera and operator access.

The default region is `eastus2`, with availability zones `1`, `2`, and `3`.
Operators need Azure CLI authentication, Terraform 1.6 or newer, permission to
create these Azure resources, and a globally unique dashboard DNS name.

### Terraform state and deployment

Production state uses the Azure backend declared in
`2-infrastructure-as-code/Terraform/versions.tf`:

- resource group: `rg-fosu-tfstate`;
- storage account: `stfosutfstatejsflw`;
- container: `tfstate`; and
- state key: `project-fosu-prod.tfstate`.

The operator needs `Storage Blob Data Contributor` on the backend storage
account. Do not change the backend or state key to bypass access errors because
that would make existing resources appear unmanaged.

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

For a new machine, create local configuration from the committed examples and
encrypt the populated variable file:

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

## Run locally

```bash
source .venv/bin/activate
uvicorn --app-dir 1-app-source-code app.main:app --reload --port 8000
streamlit run 1-app-source-code/dashboard/dashboard.py
```

Open `http://localhost:8501`. The dashboard is protected by a session login and does not request operational API data until authentication succeeds.

## Replace mock sensor with YOLO detection

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

### Switch sensors during a demonstration

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

### Lightweight infrared night detection

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

### Multi-camera mode (one process)

Use the JSON camera list (one worker thread per enabled camera):

```bash
python 1-app-source-code/scripts/yolo_sensor.py \
	--config 1-app-source-code/scripts/cameras.example.json
```

Each camera entry can define its own `source`, geolocation, confidence threshold,
post interval, and optional calibration file.

### Zone calibration for better geolocation

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

## Run with Docker

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

## Security and code quality

The `Security and quality` GitHub Actions workflow runs on pull requests and
pushes to `main` or `master`. It:

- scans the repository for vulnerable dependencies, secrets, and infrastructure
	misconfigurations with Trivy;
- builds the application image and fails on fixable high or critical image
	vulnerabilities; and
- submits source analysis to SonarQube when its repository secrets are present.

Configure a project with the key `project-fosu-smart-border` in SonarQube, then
add these GitHub Actions repository secrets:

- `SONAR_TOKEN`: a project analysis token;
- `SONAR_HOST_URL`: the externally reachable SonarQube URL, such as
	`https://sonarqube.example.com`.

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
