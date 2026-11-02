#!/bin/bash
# Build Plane images from this repo's source and (re)start the Kara stack.
#
# Images are built one at a time, with the build cache pruned in between, to
# keep peak disk usage low on the shared server. If any build fails, the
# running stack is left untouched.
#
# Usage:
#   ./deploy.sh            # git pull, build, up
#   ./deploy.sh --no-pull  # build and up from the current checkout
#
# Env overrides:
#   ENV_FILE        path to the env file. Default: ./.env next to this script
#   MIN_FREE_GB     minimum free space (GB) on Docker's disk before each build.
#                   Default: 15
#   PRUNE_BUILD_CACHE  set to 0 to keep the build cache between builds
#                   (faster rebuilds, more disk). Default: 1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE=${ENV_FILE:-$SCRIPT_DIR/.env}
MIN_FREE_GB=${MIN_FREE_GB:-15}
PRUNE_BUILD_CACHE=${PRUNE_BUILD_CACHE:-1}

# api builds the backend image shared by worker, beat-worker and migrator
BUILD_SERVICES=(api web space admin live)

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

compose() {
    $COMPOSE_CMD -f "$SCRIPT_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"
}

DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}' 2> /dev/null || echo /var/lib/docker)

free_gb() {
    local kb
    kb=$(df -Pk "$DOCKER_ROOT" 2> /dev/null | awk 'NR==2 {print $4}' || true)
    # Fall back to / when the Docker root dir is not visible to this user
    if [ -z "$kb" ]; then
        kb=$(df -Pk / | awk 'NR==2 {print $4}')
    fi
    echo $((kb / 1048576))
}

check_disk() {
    local free
    free=$(free_gb)
    if [ "$free" -lt "$MIN_FREE_GB" ]; then
        echo "Error: only ${free}GB free on Docker's disk ($DOCKER_ROOT), need ${MIN_FREE_GB}GB."
        echo "Free up space (e.g. 'docker builder prune -f', 'docker image prune -f') or set MIN_FREE_GB."
        echo "The running stack was not changed."
        exit 1
    fi
    echo "Disk: ${free}GB free on $DOCKER_ROOT"
}

prune_build_cache() {
    if [ "$PRUNE_BUILD_CACHE" = "1" ]; then
        docker builder prune -f > /dev/null
    fi
}

if [ "${1:-}" != "--no-pull" ]; then
    echo "Pulling latest source..."
    git -C "$SCRIPT_DIR" pull --ff-only
fi

echo "Deploying commit $(git -C "$SCRIPT_DIR" rev-parse --short HEAD)"

for service in "${BUILD_SERVICES[@]}"; do
    check_disk
    echo "Building $service..."
    compose build "$service"
    prune_build_cache
done

# --no-build: pull_policy "build" would otherwise rebuild every image again,
# in parallel, on up.
compose up -d --no-build --remove-orphans

# Remove dangling images left behind by previous builds
docker image prune -f > /dev/null

compose ps
