# Project Fosu Azure infrastructure

This directory provisions the Azure foundation for Project Fosu:

- Zone-spread AKS system and user node pools in a VNet
- Public Application Gateway for the dashboard only
- Internal API service and YOLO workers inside AKS
- Private Azure Database for PostgreSQL Flexible Server
- Azure Key Vault for dashboard and database secrets
- Azure Container Registry
- Point-to-site Azure VPN Gateway for camera and operator access

After Terraform finishes, use [`Ansible/README.md`](Ansible/README.md) to configure the AKS workloads and apply the private application secrets.

The default region is `eastus2`. Availability zones are configured as `["1", "2", "3"]`; use all supported zones instead of selecting one zone so a zone failure does not take down the cluster.

## Prerequisites

- Azure CLI authenticated with `az login`
- Terraform >= 1.6
- A subscription with permission to create AKS, networking, Key Vault, PostgreSQL, and VPN resources
- A globally unique DNS name for the dashboard

## Deploy

```bash
cd 2-infrastructure-as-code/Terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars. Do not commit it.
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

The PostgreSQL administrator password and dashboard password hash are supplied as sensitive Terraform variables. Prefer passing them through a CI/CD secret store or environment variables such as `TF_VAR_postgres_admin_password` and `TF_VAR_dashboard_password_hash`.

## Build and publish images

Create an Azure Container Registry token or use Azure AD-based ACR access, then build the API/dashboard image from the repository root:

```bash
az acr login --name <acr-name>
docker build -f 1-app-source-code/Dockerfile -t <acr-login-server>/project-fosu:<tag> .
docker push <acr-login-server>/project-fosu:<tag>
```

The API and dashboard should be deployed as separate Kubernetes Deployments. The YOLO worker must use the internal API URL:

```text
http://fosu-api:8000/ingest
```

## Configure the cluster

```bash
az aks get-credentials --resource-group <resource-group> --name <cluster-name>

kubectl apply -f kubernetes/namespace.yaml
# Create fosu-app-secrets through Key Vault CSI or a protected pipeline.
kubectl apply -f kubernetes/api.yaml
kubectl apply -f kubernetes/dashboard.yaml
kubectl apply -f kubernetes/yolo-sensor.yaml
kubectl apply -f kubernetes/api-network-policy.yaml
kubectl apply -f kubernetes/dashboard-ingress.yaml
```

The Application Gateway ingress exposes only the dashboard. The API is a `ClusterIP` service and PostgreSQL is reachable through its private endpoint/DNS name only. Camera sites and private operators connect through the Point-to-site VPN.

## Important production notes

- Set `DATABASE_URL` to the private PostgreSQL hostname and include `sslmode=require`.
- The application currently uses SQLite by default; do not use that default in AKS.
- Store the generated scrypt dashboard hash in Key Vault/CSI or inject it as a Kubernetes Secret from a protected pipeline.
- Restrict PostgreSQL firewall rules to the private AKS subnet. Do not enable public database access.
- Replace the example VPN client address pool and certificates before deployment.
- Use a real DNS name and TLS certificate for the public dashboard.
