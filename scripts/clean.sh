#!/bin/bash
#
# Clean all stage-env cache, snapshots, and Docker resources
# Run this script to start the network from scratch
#
# Handles root-owned files created by Docker containers:
#   1. Tries Docker-based cleanup (most reliable, no sudo needed)
#   2. Falls back to sudo rm
#   3. Falls back to plain rm (may leave root-owned files)
#

set -e

# Resolve actual script location (following symlinks)
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
STAGE_ENV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$STAGE_ENV_DIR/../.." && pwd)"
CACHE_DIR="$PROJECT_ROOT/cache"
BUILD_CACHE_DIR="$PROJECT_ROOT/build/stage-env/cache"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERR]${NC} $1"; }

# Remove a directory that may contain root-owned files (from Docker containers).
# Tries Docker-based removal first, then sudo, then plain rm.
remove_root_owned() {
    local target="$1"
    [ ! -e "$target" ] && return 0

    local parent
    parent="$(dirname "$target")"
    local base
    base="$(basename "$target")"

    # Method 1: Docker container with Alpine (handles root-owned files without sudo)
    if command -v docker &>/dev/null; then
        docker run --rm -v "$parent:/mnt/cleanup" alpine:latest \
            sh -c "rm -rf /mnt/cleanup/$base" 2>/dev/null && return 0
    fi

    # Method 2: sudo
    sudo rm -rf "$target" 2>/dev/null && return 0

    # Method 3: plain rm (will skip root-owned files)
    rm -rf "$target" 2>/dev/null || true
}

echo ""
echo "========================================="
echo "  Stage-env Full Cleanup Script"
echo "========================================="
echo ""

# Parse arguments
REMOVE_IMAGES=true
PRUNE_BUILD_CACHE=true
FORCE=false

for arg in "$@"; do
    case $arg in
        --keep-images)
            REMOVE_IMAGES=false
            shift
            ;;
        --keep-build-cache)
            PRUNE_BUILD_CACHE=false
            shift
            ;;
        -f|--force)
            FORCE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --keep-images       Keep Docker images (cf-node:*, cf-cert-generator:*)"
            echo "  --keep-build-cache  Keep Docker build cache"
            echo "  -f, --force         Skip confirmation prompt"
            echo "  -h, --help          Show this help message"
            echo ""
            exit 0
            ;;
    esac
done

# Show disk usage before cleanup
AVAIL_BEFORE=$(df --output=avail -BM / 2>/dev/null | tail -1 | tr -d ' M' || true)

# Confirmation
if [ "$FORCE" = false ]; then
    echo "This will delete:"
    echo "  - All stage-env cache data (configs, data, certs, crash-artifacts)"
    echo "  - All shard data (cache/shard-*, build/stage-env/cache/shard-*)"
    echo "  - All snapshots"
    echo "  - All artifacts and logs"
    echo "  - All cellframe-stage Docker containers and networks"
    if [ "$REMOVE_IMAGES" = true ]; then
        echo "  - All cf-node / cf-cert-generator Docker images"
    fi
    if [ "$PRUNE_BUILD_CACHE" = true ]; then
        echo "  - Docker build cache"
    fi
    echo "  - Dangling Docker volumes"
    echo "  - Generated compose files and tmp logs"
    echo ""
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        info "Cancelled"
        exit 0
    fi
fi

echo ""

# Stop and remove Docker containers
info "Stopping Docker containers..."
cd "$STAGE_ENV_DIR"
if [ -f "docker-compose.generated.yml" ]; then
    docker compose -f docker-compose.generated.yml -p cellframe-stage down --volumes --remove-orphans 2>/dev/null || true
fi
docker compose -f docker-compose.yml -p cellframe-stage down --volumes --remove-orphans 2>/dev/null || true

# Remove any stray containers (running or stopped)
info "Force stopping all cellframe-stage containers..."
docker ps -aq --filter "name=cellframe-stage" 2>/dev/null | xargs -r docker stop 2>/dev/null || true
docker ps -aq --filter "name=cellframe-stage" 2>/dev/null | xargs -r docker rm -f 2>/dev/null || true
success "Docker containers stopped and removed"

# Remove Docker networks
info "Removing Docker networks..."
NETWORKS=$(docker network ls --filter "name=cellframe-stage" -q 2>/dev/null || true)
if [ -n "$NETWORKS" ]; then
    echo "$NETWORKS" | xargs -r docker network rm 2>/dev/null || true
fi
success "Docker networks removed"

# Remove Docker images if requested
if [ "$REMOVE_IMAGES" = true ]; then
    info "Removing Docker images..."
    docker images --filter "reference=cf-node:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=cf-node" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=cf-cert-generator:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=cf-cert-generator" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=cf-tools:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=docker.io/library/cf-node:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=docker.io/library/cf-cert-generator:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images | grep -E "^cf-node|^cf-cert-generator|^cf-tools" | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true

    REMAINING=$(docker images | grep -E "^cf-node|^cf-cert-generator|^cf-tools" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
        warning "Some images could not be removed (may be in use):"
        echo "$REMAINING"
    else
        success "Docker images removed"
    fi
fi

# Remove dangling volumes
info "Removing dangling Docker volumes..."
docker volume prune -f 2>/dev/null || true
success "Dangling volumes removed"

# Prune Docker build cache
if [ "$PRUNE_BUILD_CACHE" = true ]; then
    info "Pruning Docker build cache..."
    docker builder prune -a -f 2>/dev/null || true
    success "Docker build cache pruned"
fi

# Clean primary cache directory (PROJECT_ROOT/cache)
info "Cleaning cache ($CACHE_DIR)..."
if [ -d "$CACHE_DIR" ]; then
    for subdir in configs data certs crash-artifacts cellframe-packages; do
        remove_root_owned "$CACHE_DIR/$subdir"
    done
    # Clean shard directories
    for shard_dir in "$CACHE_DIR"/shard-*; do
        [ -d "$shard_dir" ] && remove_root_owned "$shard_dir"
    done
    success "cache cleaned"
else
    warning "cache directory not found: $CACHE_DIR"
fi

# Clean build/stage-env cache (separate cache tree used by test runner)
if [ -d "$BUILD_CACHE_DIR" ]; then
    info "Cleaning build cache ($BUILD_CACHE_DIR)..."
    for subdir in configs data certs crash-artifacts cellframe-packages; do
        remove_root_owned "$BUILD_CACHE_DIR/$subdir"
    done
    for shard_dir in "$BUILD_CACHE_DIR"/shard-*; do
        [ -d "$shard_dir" ] && remove_root_owned "$shard_dir"
    done
    success "build cache cleaned"
fi

# Clean snapshots
info "Cleaning snapshots..."
for snap_dir in "$CACHE_DIR/snapshots" "$BUILD_CACHE_DIR/snapshots"; do
    if [ -d "$snap_dir" ]; then
        remove_root_owned "$snap_dir"
        mkdir -p "$snap_dir"
    fi
done
success "Snapshots cleaned"

# Clean artifacts
info "Cleaning artifacts..."
for art_dir in "$CACHE_DIR/artifacts" "$PROJECT_ROOT/build/stage-env/artifacts"; do
    if [ -d "$art_dir" ]; then
        rm -rf "$art_dir"/* 2>/dev/null || true
    fi
done
success "Artifacts cleaned"

# Clean logs
info "Cleaning logs..."
for log_dir in "$CACHE_DIR/logs" "$PROJECT_ROOT/build/stage-env/logs"; do
    if [ -d "$log_dir" ]; then
        rm -rf "$log_dir"/* 2>/dev/null || true
    fi
done
success "Logs cleaned"

# Clean generated compose files
info "Cleaning generated files..."
rm -f "$STAGE_ENV_DIR/docker-compose.generated.yml" 2>/dev/null || true
rm -f "$STAGE_ENV_DIR"/docker-compose.shard-*.yml 2>/dev/null || true
success "Generated files cleaned"

# Clean tmp logs
info "Cleaning tmp logs..."
rm -f /tmp/cellframe-stage-*.log 2>/dev/null || true
rm -f /tmp/final_test.log 2>/dev/null || true
success "Tmp logs cleaned"

# Show disk usage after cleanup
AVAIL_AFTER=$(df --output=avail -BM / 2>/dev/null | tail -1 | tr -d ' M' || true)
FREED=""
if [ -n "$AVAIL_BEFORE" ] && [ -n "$AVAIL_AFTER" ]; then
    FREED_MB=$((AVAIL_AFTER - AVAIL_BEFORE))
    if [ "$FREED_MB" -gt 1024 ]; then
        FREED=" (freed $(( FREED_MB / 1024 ))GB)"
    elif [ "$FREED_MB" -gt 0 ]; then
        FREED=" (freed ${FREED_MB}MB)"
    fi
fi

echo ""
echo "========================================="
success "Cleanup complete!${FREED} You can now run:"
echo ""
echo "  ./run.sh --keep-running"
echo ""
echo "========================================="
