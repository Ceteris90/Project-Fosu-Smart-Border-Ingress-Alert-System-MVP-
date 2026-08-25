# Project Fosu Ansible configuration

This directory configures the AKS workload after the Azure resources have been
created by Terraform. Terraform owns cloud infrastructure; Ansible owns the
Kubernetes namespace, private application secret, deployments, and ingress.

## Prerequisites

- Ansible >= 2.15
- Azure CLI authenticated with `az login`
- `kubectl` configured locally or available on PATH
- Python package `kubernetes`
- Collections from `requirements.yml`
- Network access to the private AKS API server, normally through the Azure VPN
- Terraform outputs available from `../Terraform`

Install collections and the Python client:

```bash
ansible-galaxy collection install -r requirements.yml
python3 -m pip install kubernetes
```

## Configure variables

Copy the example files and fill in values through a protected secret store or
Ansible Vault. Do not commit populated variable files:

```bash
cp inventory.ini.example inventory.ini
cp group_vars/all.example.yml group_vars/all.yml
ansible-vault encrypt group_vars/all.yml
```

Set the ACR image once it has been built and pushed. The database URL should use
the private PostgreSQL hostname and `sslmode=require`.

## Run

```bash
ansible-playbook -i inventory.ini site.yml --ask-vault-pass
```

The playbook:

1. Gets private AKS credentials with Azure CLI.
2. Creates the `project-fosu` namespace.
3. Creates or updates the application Secret from protected variables.
4. Applies the API, dashboard, YOLO sensor, network policy, and dashboard ingress.
5. Waits for the API and dashboard deployments to become ready.

The dashboard is exposed through the public Application Gateway. The API stays
as a private `ClusterIP`; cameras send to `http://fosu-api:8000/ingest` over the
VPN/private network.
