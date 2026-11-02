#!/bin/bash
# Build Plane images from this repo's source and (re)start the stack.
#
# Usage:
#   ./deploy.sh            # git pull, build, up
#   ./deploy.sh --no-pull  # build and up from the current checkout
#
# Env overrides:
#   PROJECT_NAME  compose project name; must match the existing install so the
#                 same volumes (pgdata, uploads, ...) are reused. Default: plane-app
#   ENV_FILE      path to plane.env. Default: ./plane.env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME=${PROJECT_NAME:-plane-app}
ENV_FILE=${ENV_FILE:-$SCRIPT_DIR/plane.env}

if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: env file not found at $ENV_FILE"
    echo "Copy it from the existing install, e.g. cp ~/plane-app/plane.env $SCRIPT_DIR/plane.env"
    exit 1
fi

if [ "${1:-}" != "--no-pull" ]; then
    echo "Pulling latest source..."
    git -C "$SCRIPT_DIR" pull --ff-only
fi

echo "Deploying commit $(git -C "$SCRIPT_DIR" rev-parse --short HEAD) as project '$PROJECT_NAME'"

compose() {
    $COMPOSE_CMD -p "$PROJECT_NAME" \
        -f "$SCRIPT_DIR/docker-compose.yml" \
        -f "$SCRIPT_DIR/docker-compose.build.yml" \
        --env-file "$ENV_FILE" "$@"
}

compose build
compose up -d --remove-orphans

# Remove dangling images left behind by previous builds
docker image prune -f > /dev/null

compose ps
