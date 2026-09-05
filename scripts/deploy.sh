#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${FOSU_DEPLOY_CONFIG:-${SCRIPT_DIR}/deployment.config}"
TERRAFORM_DIR="${PROJECT_ROOT}/2-infrastructure-as-code/Terraform"
ANSIBLE_DIR="${PROJECT_ROOT}/2-infrastructure-as-code/Ansible"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.yaml"
DOCKERFILE="${PROJECT_ROOT}/1-app-source-code/Dockerfile"

arguments=("$@")
for ((argument_index = 0; argument_index < ${#arguments[@]}; argument_index++)); do
    if [[ "${arguments[argument_index]}" == "--config" ]]; then
        ((argument_index + 1 < ${#arguments[@]})) || {
            printf 'ERROR: --config requires a path\n' >&2
            exit 1
        }
        CONFIG_FILE="${arguments[argument_index + 1]}"
    fi
done

DRY_RUN=false
SKIP_BUILD=false
SKIP_SCAN=false
SKIP_TERRAFORM=false
AUTO_APPROVE=false
CONFIRM_DESTROY=false

if [[ -f "${CONFIG_FILE}" ]]; then
    # shellcheck source=/dev/null
    source "${CONFIG_FILE}"
fi

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ceteris90/project-fosu}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
K8S_NAMESPACE="${K8S_NAMESPACE:-project-fosu}"
KUBECONFIG_PATH="${KUBECONFIG_PATH:-/tmp/project-fosu-kubeconfig}"
ANSIBLE_INVENTORY="${ANSIBLE_INVENTORY:-${ANSIBLE_DIR}/inventory.ini}"
TRIVY_SEVERITY="${TRIVY_SEVERITY:-HIGH,CRITICAL}"
LOG_FILE="${LOG_FILE:-${PROJECT_ROOT}/.local/logs/deploy.log}"

readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

usage() {
    cat <<'EOF'
PROJECT FOSU DEPLOYMENT ORCHESTRATOR

Usage
    scripts/deploy.sh [options] <command>

Commands
    COMMAND     DESCRIPTION
    preflight   Validate tools, files, Azure login, and configuration
    local       Build and start the Docker Compose stack
    build       Build the application image
    scan        Run Trivy source and image scans
    infra       Initialize, validate, plan, and apply Terraform
    app         Push the image and deploy workloads to AKS with Ansible
    deploy      Run preflight, build, scan, Terraform, and AKS deployment
    status      Show local and AKS deployment status
    destroy     Destroy Azure infrastructure (requires --confirm-destroy)
    down        Stop the local Docker Compose stack without deleting volumes

Options
    OPTION               DESCRIPTION
    --config PATH        Load a deployment config file
    --dry-run            Print mutating commands without running them
    --skip-build         Reuse an existing image
    --skip-scan          Skip Trivy scans
    --skip-terraform     Reuse existing Azure infrastructure
    --auto-approve       Apply Terraform without an approval prompt
    --confirm-destroy    Allow the destructive Terraform destroy command
    -h, --help           Show this help

Secrets remain in ignored Terraform variables, environment variables, Azure
Key Vault, Docker's credential store, and Ansible Vault. Do not put secrets in
deployment.config.
EOF
}

log() {
    local level="$1"
    local color="$2"
    local timestamp
    shift 2
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    mkdir -p "$(dirname "${LOG_FILE}")"
    printf '%b[%s] %b%s%b %s\n' "${BLUE}" "${timestamp}" "${color}" "${level}" "${NC}" "$*"
    printf '[%s] %s %s\n' "${timestamp}" "${level}" "$*" >> "${LOG_FILE}"
}

info() { log INFO "${GREEN}" "$@"; }
warn() { log WARN "${YELLOW}" "$@"; }
die() { log ERROR "${RED}" "$@" >&2; exit 1; }

section() {
    local title="$*"
    local width=72
    local rule
    rule="$(printf '%*s' "${width}" '' | tr ' ' '=')"
    printf '\n%b%s\n  %s\n%s%b\n' "${BLUE}" "${rule}" "${title}" "${rule}" "${NC}"
}

table_rule() {
    local widths="$1"
    local width
    local rule='  +'
    for width in ${widths}; do
        rule+="$(printf '%*s' "$((width + 2))" '' | tr ' ' '-')+"
    done
    printf '%s\n' "${rule}"
}

table_row() {
    local widths="$1"
    shift
    local -a column_widths
    local -a values=("$@")
    local column
    local line
    local line_count=1
    local offset
    local value
    read -ra column_widths <<< "${widths}"

    for column in "${!column_widths[@]}"; do
        value="${values[column]:-}"
        if (( (${#value} + column_widths[column] - 1) / column_widths[column] > line_count )); then
            line_count=$(((${#value} + column_widths[column] - 1) / column_widths[column]))
        fi
    done

    for ((line = 0; line < line_count; line++)); do
        printf '  |'
        for column in "${!column_widths[@]}"; do
            value="${values[column]:-}"
            offset=$((line * column_widths[column]))
            printf " %-*s |" "${column_widths[column]}" "${value:offset:column_widths[column]}"
        done
        printf '\n'
    done
}

table_header() {
    local widths="$1"
    shift
    table_rule "${widths}"
    printf '%b' "${BLUE}"
    table_row "${widths}" "$@"
    printf '%b' "${NC}"
    table_rule "${widths}"
}

table_end() {
    table_rule "$1"
}

key_value() {
    table_row '18 45' "$1" "$2"
}

display_path() {
    local path="$1"
    if [[ "${path}" == "${PROJECT_ROOT}"/* ]]; then
        printf '%s' "${path#"${PROJECT_ROOT}/"}"
    else
        printf '%s' "${path}"
    fi
}

command_preview() {
    local argument
    local quoted
    local line='  $'
    local max_width=72
    printf '%b  DRY RUN%b\n' "${YELLOW}" "${NC}"
    for argument in "$@"; do
        if [[ "${argument}" == "${PROJECT_ROOT}"/* ]]; then
            quoted="\${PROJECT_ROOT}/${argument#"${PROJECT_ROOT}/"}"
        else
            printf -v quoted '%q' "${argument}"
        fi
        if (( ${#line} + ${#quoted} + 1 > max_width )); then
            printf '%s \\\n' "${line}"
            line="      ${quoted}"
        else
            line+=" ${quoted}"
        fi
    done
    printf '%s\n' "${line}"
}

run() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        command_preview "$@"
        return 0
    fi
    "$@"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_file() {
    [[ -f "$1" ]] || die "Required file not found: $1"
}

azure_logged_in() {
    az account show --output none >/dev/null 2>&1
}

preflight() {
    section "Preflight"
    require_file "${DOCKERFILE}"
    require_file "${COMPOSE_FILE}"
    require_file "${TERRAFORM_DIR}/main.tf"
    require_file "${ANSIBLE_DIR}/site.yml"
    require_file "${ANSIBLE_INVENTORY}"

    local tool
    for tool in docker terraform az kubectl kubelogin ansible-playbook; do
        require_command "${tool}"
    done
    docker info >/dev/null 2>&1 || die "Docker daemon is unavailable"
    azure_logged_in || die "Azure CLI is not authenticated; run 'az login'"

    if [[ ! -f "${TERRAFORM_DIR}/terraform.tfvars" ]]; then
        warn "terraform.tfvars is absent; required TF_VAR_* values must be exported"
    fi
    if [[ -z "${TF_VAR_dashboard_tls_certificate_base64:-}" && ! -s "${TERRAFORM_DIR}/dashboard.pfx" ]]; then
        die "Set TF_VAR_dashboard_tls_certificate_base64 or provide ${TERRAFORM_DIR}/dashboard.pfx"
    fi

    printf '\n'
    table_header '18 8 34' "CHECK" "STATUS" "DETAIL"
    table_row '18 8 34' "Required files" "PASS" "Docker, Terraform, Ansible"
    table_row '18 8 34' "Required tools" "PASS" "All commands available"
    table_row '18 8 34' "Docker daemon" "PASS" "Available"
    table_row '18 8 34' "Azure session" "PASS" "Authenticated"
    table_end '18 8 34'
    printf '\n'
    table_header '18 45' "SETTING" "VALUE"
    key_value "Image" "${IMAGE}"
    key_value "Namespace" "${K8S_NAMESPACE}"
    key_value "Kubeconfig" "${KUBECONFIG_PATH}"
    key_value "Config" "$(display_path "${CONFIG_FILE}")"
    table_end '18 45'
    info "Preflight passed"
}

prepare_terraform_environment() {
    if [[ -z "${TF_VAR_dashboard_tls_certificate_base64:-}" && -s "${TERRAFORM_DIR}/dashboard.pfx" ]]; then
        export TF_VAR_dashboard_tls_certificate_base64
        TF_VAR_dashboard_tls_certificate_base64="$(base64 -w0 "${TERRAFORM_DIR}/dashboard.pfx")"
    fi
}

build_image() {
    if [[ "${SKIP_BUILD}" == "true" ]]; then
        warn "Skipping image build"
        return 0
    fi
    section "Build image"
    run docker build --file "${DOCKERFILE}" --tag "${IMAGE}" "${PROJECT_ROOT}"
}

scan_source() {
    require_command trivy
    run trivy fs \
        --scanners vuln,secret,misconfig \
        --severity "${TRIVY_SEVERITY}" \
        --ignore-unfixed \
        --timeout 10m \
        --skip-dirs .venv \
        --skip-dirs venv \
        --skip-dirs .local \
        --skip-dirs 2-infrastructure-as-code/Ansible/.collections \
        --skip-files '*.pt' \
        "${PROJECT_ROOT}"
}

scan_image() {
    require_command trivy
    if [[ "${DRY_RUN}" != "true" ]] && ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
        die "Image ${IMAGE} does not exist; run the build command first"
    fi
    run trivy image \
        --scanners vuln \
        --severity "${TRIVY_SEVERITY}" \
        --ignore-unfixed \
        --exit-code 1 \
        --timeout 10m \
        "${IMAGE}"
}

scan_all() {
    if [[ "${SKIP_SCAN}" == "true" ]]; then
        warn "Skipping Trivy scans"
        return 0
    fi
    section "Trivy source scan"
    scan_source
    section "Trivy image scan"
    scan_image
}

push_image() {
    section "Push image"
    run docker push "${IMAGE}"
}

provision_infrastructure() {
    if [[ "${SKIP_TERRAFORM}" == "true" ]]; then
        warn "Skipping Terraform"
        return 0
    fi
    section "Provision Azure infrastructure"
    prepare_terraform_environment
    run terraform -chdir="${TERRAFORM_DIR}" init
    run terraform -chdir="${TERRAFORM_DIR}" validate
    run terraform -chdir="${TERRAFORM_DIR}" plan -out=tfplan
    if [[ "${AUTO_APPROVE}" == "true" ]]; then
        run terraform -chdir="${TERRAFORM_DIR}" apply -auto-approve tfplan
    else
        run terraform -chdir="${TERRAFORM_DIR}" apply tfplan
    fi
}

deploy_application() {
    section "Deploy application to private AKS"
    require_command ansible-playbook
    require_file "${ANSIBLE_INVENTORY}"
    export KUBECONFIG="${KUBECONFIG_PATH}"
    local -a ansible_command=(
        ansible-playbook
        -i "${ANSIBLE_INVENTORY}"
        "${ANSIBLE_DIR}/site.yml"
        --extra-vars "image_repository=${IMAGE_REPOSITORY}"
        --extra-vars "image_tag=${IMAGE_TAG}"
        --extra-vars "fosu_namespace=${K8S_NAMESPACE}"
    )

    if [[ -n "${ANSIBLE_VAULT_PASSWORD_FILE:-}" ]]; then
        require_file "${ANSIBLE_VAULT_PASSWORD_FILE}"
        ansible_command+=(--vault-password-file "${ANSIBLE_VAULT_PASSWORD_FILE}")
    else
        ansible_command+=(--ask-vault-pass)
    fi

    if [[ "${DRY_RUN}" == "true" ]]; then
        run "${ansible_command[@]}"
        return 0
    fi

    "${ansible_command[@]}"
}

deploy_cloud() {
    preflight
    build_image
    scan_all
    push_image
    provision_infrastructure
    deploy_application
    show_status
}

deploy_local() {
    section "Deploy local stack"
    require_command docker
    run docker compose --file "${COMPOSE_FILE}" up --build --detach
    if [[ "${DRY_RUN}" != "true" ]]; then
        show_local_status
    fi
}

show_local_status() {
    printf '%bLocal services%b\n' "${BLUE}" "${NC}"
    if [[ -n "$(docker compose --file "${COMPOSE_FILE}" ps --status running --quiet 2>/dev/null)" ]]; then
        table_header '16 9 7 30' "SERVICE" "STATE" "HEALTH" "PORTS"
        while IFS=$'\t' read -r service state health ports; do
            table_row '16 9 7 30' "${service}" "${state}" "${health:--}" "${ports:--}"
        done < <(docker compose --file "${COMPOSE_FILE}" ps --format '{{.Service}}\t{{.State}}\t{{.Health}}\t{{.Ports}}')
        table_end '16 9 7 30'
    else
        table_header '18 45' "STATUS" "DETAIL"
        table_row '18 45' "Not running" "No local Compose services"
        table_end '18 45'
    fi
}

show_aks_status() {
    printf '\n%bPrivate AKS workloads%b\n' "${BLUE}" "${NC}"
    if [[ ! -f "${KUBECONFIG_PATH}" ]] || ! kubectl --request-timeout=5s --kubeconfig "${KUBECONFIG_PATH}" get namespace "${K8S_NAMESPACE}" >/dev/null 2>&1; then
        table_header '18 45' "STATUS" "DETAIL"
        table_row '18 45' "Unavailable" "Connect VPN or run app deployment"
        table_end '18 45'
        return 0
    fi

    table_header '26 8 10 6' "DEPLOYMENT" "READY" "AVAILABLE" "AGE"
    while read -r name ready updated available age; do
        table_row '26 8 10 6' "${name}" "${ready}" "${available}" "${age}"
    done < <(kubectl --request-timeout=5s --kubeconfig "${KUBECONFIG_PATH}" -n "${K8S_NAMESPACE}" get deployments --no-headers)
    table_end '26 8 10 6'

    printf '\n'
    table_header '33 7 9 8' "POD" "READY" "STATUS" "RESTARTS"
    while IFS=$'\t' read -r name ready status restarts; do
        table_row '33 7 9 8' "${name}" "${ready}" "${status}" "${restarts}"
    done < <(kubectl --request-timeout=5s --kubeconfig "${KUBECONFIG_PATH}" -n "${K8S_NAMESPACE}" get pods --no-headers | awk '{print $1 "\t" $2 "\t" $3 "\t" $4}')
    table_end '33 7 9 8'
}

show_endpoints() {
    printf '\n%bEndpoints%b\n' "${BLUE}" "${NC}"
    table_header '18 45' "ENDPOINT" "URL"

    if terraform -chdir="${TERRAFORM_DIR}" output -raw dashboard_hostname >/dev/null 2>&1; then
        table_row '18 45' "Dashboard" "https://$(terraform -chdir="${TERRAFORM_DIR}" output -raw dashboard_hostname)"
    else
        table_row '18 45' "Dashboard" "Unavailable"
    fi
    table_row '18 45' "Local API" "http://127.0.0.1:8000"
    table_row '18 45' "Local dashboard" "http://127.0.0.1:8501"
    table_end '18 45'
}

show_status() {
    section "Deployment status"
    show_local_status
    show_aks_status
    show_endpoints

    printf '\n'
    table_header '18 45' "SETTING" "VALUE"
    key_value "Namespace" "${K8S_NAMESPACE}"
    key_value "Image" "${IMAGE}"
    key_value "Log file" "$(display_path "${LOG_FILE}")"
    table_end '18 45'
}

stop_local() {
    section "Stop local stack"
    run docker compose --file "${COMPOSE_FILE}" down
}

destroy_infrastructure() {
    [[ "${CONFIRM_DESTROY}" == "true" ]] || die "Refusing to destroy Azure resources without --confirm-destroy"
    section "Destroy Azure infrastructure"
    prepare_terraform_environment
    if [[ "${AUTO_APPROVE}" == "true" ]]; then
        run terraform -chdir="${TERRAFORM_DIR}" destroy -auto-approve
    else
        run terraform -chdir="${TERRAFORM_DIR}" destroy
    fi
}

COMMAND=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            [[ $# -ge 2 ]] || die "--config requires a path"
            CONFIG_FILE="$2"
            [[ -f "${CONFIG_FILE}" ]] || die "Configuration file not found: ${CONFIG_FILE}"
            shift 2
            ;;
        --dry-run) DRY_RUN=true; shift ;;
        --skip-build) SKIP_BUILD=true; shift ;;
        --skip-scan) SKIP_SCAN=true; shift ;;
        --skip-terraform) SKIP_TERRAFORM=true; shift ;;
        --auto-approve) AUTO_APPROVE=true; shift ;;
        --confirm-destroy) CONFIRM_DESTROY=true; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) die "Unknown option: $1" ;;
        *)
            [[ -z "${COMMAND}" ]] || die "Only one command may be specified"
            COMMAND="$1"
            shift
            ;;
    esac
done

case "${COMMAND:-deploy}" in
    preflight) preflight ;;
    local) deploy_local ;;
    build) build_image ;;
    scan) scan_all ;;
    infra) preflight; provision_infrastructure ;;
    app) preflight; build_image; scan_all; push_image; deploy_application; show_status ;;
    deploy) deploy_cloud ;;
    status) show_status ;;
    destroy) destroy_infrastructure ;;
    down) stop_local ;;
    *) usage; die "Unknown command: ${COMMAND}" ;;
esac
