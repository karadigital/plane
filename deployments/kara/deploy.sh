#!/bin/bash
# Build Plane images from this repo's source and (re)start the Kara stack.
#
# Usage:
#   ./deploy.sh            # git pull, build, up
#   ./deploy.sh --no-pull  # build and up from the current checkout
#
# Env overrides:
#   ENV_FILE  path to the env file. Default: ./.env next to this script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE=${ENV_FILE:-$SCRIPT_DIR/.env}

if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    COMPOSE_CMD="docker compose"
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: env file not found at $ENV_FILE"
    echo "Copy it from the old install, e.g. cp ~/plane/.env $SCRIPT_DIR/.env"
    exit 1
fi

if [ "${1:-}" != "--no-pull" ]; then
    echo "Pulling latest source..."
    git -C "$SCRIPT_DIR" pull --ff-only
fi

echo "Deploying commit $(git -C "$SCRIPT_DIR" rev-parse --short HEAD)"

compose() {
    $COMPOSE_CMD -f "$SCRIPT_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"
}

compose build
compose up -d --remove-orphans

# Remove dangling images left behind by previous builds
docker image prune -f > /dev/null

compose ps
