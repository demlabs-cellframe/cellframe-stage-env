#!/bin/bash
#
# Clean all stage-env cache, snapshots, and Docker resources
# Run this script to start the network from scratch
#

set -e

# Resolve actual script location (following symlinks)
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
STAGE_ENV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$STAGE_ENV_DIR/../.." && pwd)"
CACHE_DIR="$PROJECT_ROOT/cache"

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

echo ""
echo "========================================="
echo "  Stage-env Full Cleanup Script"
echo "========================================="
echo ""

# Parse arguments
REMOVE_IMAGES=true
FORCE=false
DOCKER_PRUNE_ALL=false

for arg in "$@"; do
    case $arg in
        --keep-images)
            REMOVE_IMAGES=false
            shift
            ;;
        --docker-prune-all)
            DOCKER_PRUNE_ALL=true
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
            echo "  --keep-images      Keep Docker images (cf-node:*, cf-cert-generator:*)"
            echo "  --docker-prune-all  After cleanup, run: docker system prune -a -f"
            echo "  -f, --force        Skip confirmation prompt"
            echo "  -h, --help         Show this help message"
            echo ""
            exit 0
            ;;
    esac
done

# Confirmation
if [ "$FORCE" = false ]; then
    echo "This will delete:"
    echo "  - cache/configs, cache/data, cache/certs, cache/crash-artifacts"
    echo "  - cache/snapshots"
    echo "  - cache/artifacts"
    echo "  - cache/logs"
    echo "  - All cellframe-stage Docker containers"
    echo "  - All cellframe-stage Docker networks"
    echo "  - All cf-node Docker images"
    echo "  - cf-cert-generator Docker image"
    echo "  - Dangling Docker volumes"
    if [ "$REMOVE_IMAGES" = false ]; then
        echo ""
        echo "  (Images will be KEPT due to --keep-images flag)"
    fi
    if [ "$DOCKER_PRUNE_ALL" = true ]; then
        echo ""
        echo "  Also run: docker system prune -a -f (removes all unused images — high disk savings)"
    fi
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
    # Remove by various possible reference names
    docker images --filter "reference=cf-node:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=cf-node" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=cf-cert-generator:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=cf-cert-generator" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    # Also try with full docker.io prefix
    docker images --filter "reference=docker.io/library/cf-node:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=docker.io/library/cf-cert-generator:*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
    # Fallback: find by name pattern and remove by ID
    docker images | grep -E "^cf-node|^cf-cert-generator" | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true
    
    # Verify images are removed
    REMAINING=$(docker images | grep -E "^cf-node|^cf-cert-generator" 2>/dev/null || true)
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

# Clean cache directory (configs, data, certs, crash-artifacts)
info "Cleaning cache..."
if [ -d "$CACHE_DIR" ]; then
    # Some files may be owned by root (from Docker), use sudo if needed
    sudo rm -rf "$CACHE_DIR/configs" 2>/dev/null || rm -rf "$CACHE_DIR/configs" 2>/dev/null || true
    sudo rm -rf "$CACHE_DIR/data" 2>/dev/null || rm -rf "$CACHE_DIR/data" 2>/dev/null || true
    sudo rm -rf "$CACHE_DIR/certs" 2>/dev/null || rm -rf "$CACHE_DIR/certs" 2>/dev/null || true
    sudo rm -rf "$CACHE_DIR/crash-artifacts" 2>/dev/null || rm -rf "$CACHE_DIR/crash-artifacts" 2>/dev/null || true
    success "cache cleaned (configs, data, certs, crash-artifacts)"
else
    warning "cache directory not found: $CACHE_DIR"
fi

# Clean snapshots
info "Cleaning snapshots..."
if [ -d "$CACHE_DIR/snapshots" ]; then
    sudo rm -rf "$CACHE_DIR/snapshots"/* 2>/dev/null || rm -rf "$CACHE_DIR/snapshots"/* 2>/dev/null || true
    success "cache/snapshots cleaned"
else
    warning "cache/snapshots not found"
fi

# Clean artifacts
info "Cleaning artifacts..."
if [ -d "$CACHE_DIR/artifacts" ]; then
    rm -rf "$CACHE_DIR/artifacts"/* 2>/dev/null || true
    success "cache/artifacts cleaned"
fi

# Clean logs
info "Cleaning logs..."
if [ -d "$CACHE_DIR/logs" ]; then
    rm -rf "$CACHE_DIR/logs"/* 2>/dev/null || true
    success "cache/logs cleaned"
fi

# Clean generated compose file
info "Cleaning generated files..."
rm -f "$STAGE_ENV_DIR/docker-compose.generated.yml" 2>/dev/null || true
success "Generated files cleaned"

# Clean tmp logs
info "Cleaning tmp logs..."
rm -f /tmp/cellframe-stage-*.log 2>/dev/null || true
rm -f /tmp/final_test.log 2>/dev/null || true
success "Tmp logs cleaned"

if [ "$DOCKER_PRUNE_ALL" = true ]; then
    info "docker system prune -a -f ..."
    docker system prune -a -f 2>/dev/null || warning "docker system prune failed (check Docker daemon)"
fi

echo ""
echo "========================================="
success "Cleanup complete! You can now run:"
echo ""
echo "  ./scripts/run.sh --start-only"
echo "  # or: ./scripts/run.sh --keep-running"
echo ""
echo "========================================="
