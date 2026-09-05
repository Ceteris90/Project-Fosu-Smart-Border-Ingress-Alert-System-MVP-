#!/usr/bin/env bash
set -u

kubeconfig_path="${KUBECONFIG_PATH:-/tmp/project-fosu-kubeconfig}"
namespace="${KUBERNETES_NAMESPACE:-project-fosu}"
local_port="${LOCAL_PORT:-8000}"
remote_port="${REMOTE_PORT:-8000}"
reconnect_delay="${RECONNECT_DELAY:-3}"
healthcheck_url="${HEALTHCHECK_URL:-http://127.0.0.1:${local_port}/}"
healthcheck_interval="${HEALTHCHECK_INTERVAL:-5}"
healthcheck_timeout="${HEALTHCHECK_TIMEOUT:-3}"
healthcheck_failures="${HEALTHCHECK_FAILURES:-3}"
startup_grace="${STARTUP_GRACE:-5}"
lock_file="${XDG_RUNTIME_DIR:-/tmp}/project-fosu-port-forward-${local_port}.lock"
child_pid=""

exec 9>"$lock_file"
if ! flock -n 9; then
	echo "Another API port-forward wrapper is already using port ${local_port}." >&2
	exit 1
fi

cleanup() {
	if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
		kill "$child_pid" 2>/dev/null || true
		wait "$child_pid" 2>/dev/null || true
	fi
}

trap 'cleanup; exit 0' INT TERM

while true; do
	echo "Forwarding 127.0.0.1:${local_port} to service/fosu-api:${remote_port}"
	kubectl \
		--kubeconfig "$kubeconfig_path" \
		-n "$namespace" \
		port-forward \
		--address 127.0.0.1 \
		service/fosu-api \
		"${local_port}:${remote_port}" &
	child_pid=$!
	failed_healthchecks=0
	sleep "$startup_grace"

	while kill -0 "$child_pid" 2>/dev/null; do
		if curl --fail --silent --show-error \
			--connect-timeout "$healthcheck_timeout" \
			--max-time "$healthcheck_timeout" \
			"$healthcheck_url" >/dev/null 2>&1; then
			failed_healthchecks=0
		else
			((failed_healthchecks += 1))
			echo "Port-forward health check failed (${failed_healthchecks}/${healthcheck_failures})" >&2
			if ((failed_healthchecks >= healthcheck_failures)); then
				echo "Port-forward is unresponsive; restarting it" >&2
				kill "$child_pid" 2>/dev/null || true
				break
			fi
		fi
		sleep "$healthcheck_interval"
	done

	wait "$child_pid"
	status=$?
	child_pid=""
	echo "Port-forward exited with status ${status}; retrying in ${reconnect_delay}s" >&2
	sleep "$reconnect_delay"
done