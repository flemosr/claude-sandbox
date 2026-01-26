#!/bin/bash
# Claude Code Sandbox - runs in Docker with current directory mounted

set -e

yolo_flag=""
firewalled=false
args=()

for arg in "$@"; do
  case "$arg" in
    --yolo)
      yolo_flag="--dangerously-skip-permissions"
      ;;
    --firewalled)
      firewalled=true
      ;;
    *)
      args+=("$arg")
      ;;
  esac
done

project_name="${PWD##*/}"
docker_args=(
  --rm -it
  -v "$(pwd):/workspaces/${project_name}"
  -w "/workspaces/${project_name}"
  -v claude-sandbox-config:/home/claude/.claude
  -e TERM=xterm-256color
  --add-host=host.docker.internal:host-gateway
)

if $firewalled; then
  docker_args+=(--cap-add=NET_ADMIN -e ENABLE_FIREWALL=1 --user root)
  docker run "${docker_args[@]}" local/claude-sandbox \
    /opt/entrypoint.sh $yolo_flag "${args[@]}"
else
  docker run "${docker_args[@]}" local/claude-sandbox \
    claude $yolo_flag "${args[@]}"
fi
