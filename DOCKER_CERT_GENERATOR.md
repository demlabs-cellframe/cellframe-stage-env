# Docker-Based Certificate Generator

## Overview

The certificate generator (`cf-cert-generator`) now runs in Docker for **complete cross-platform compatibility**. This eliminates the need to build native binaries on different platforms.

## Benefits

✅ **Cross-platform** - works on Linux, macOS, Windows (with Docker)  
✅ **No local compilation** - no need to install build tools on host  
✅ **Reproducible** - same certificates on all platforms  
✅ **Isolated** - no interference with host system  
✅ **Automated** - builds image automatically when needed  

## How It Works

```
┌─────────────────┐
│  stage-env CLI  │
│  (Python)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CertGenerator   │ ← Detects if Docker image exists
│  (Python)       │   If not - builds it automatically
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│ Docker Container                            │
│  ┌───────────────────────────────────────┐  │
│  │ cf-cert-generator (C binary)          │  │
│  │  - DAP SDK crypto libraries           │  │
│  │  - Post-quantum algorithms (Dilithium)│  │
│  │  - Generates .dcert files             │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  Mounted: host:/cache/certs → /output      │
└─────────────────────────────────────────────┘
         │
         ▼
    host: cache/certs/
      ├── node1/
      │   ├── node-addr.dcert
      │   └── stagenet.master.0.dcert
      ├── node2/
      └── ...
```

## Usage

### Automatic (Recommended)

The cert generator Docker image builds **automatically** when you first run:

```bash
# Just use certs command - Docker image builds if needed
./stage-env certs --nodes 6 --validators 3
```

First run output:
```
• Building certificate generator Docker image...
[...docker build output...]
✓ Certificate generator image built
• Generating 6 node certificates using Docker...
✓ Generated 6 node + 0 validator certificates
```

Subsequent runs (image already exists):
```
• Generating 6 node certificates using Docker...
✓ Generated 6 node + 0 validator certificates
```

### Manual Docker Build

To pre-build the image manually:

```bash
# From project root
docker build \
  -f tests/stage-env/Dockerfile.cert-generator \
  -t cf-cert-generator:latest \
  .
```

### Direct Docker Usage

To run cert generator directly:

```bash
# Generate certificates directly
docker run --rm \
  -v $(pwd)/tests/stage-env/cache/certs:/output \
  -u $(id -u):$(id -g) \
  cf-cert-generator:latest \
  /output 6 stagenet 0x1234

# Arguments:
#   /output    - output directory inside container
#   6          - number of nodes
#   stagenet   - network name
#   0x1234     - network ID
```

## Architecture

### Dockerfile.cert-generator

Multi-stage build:

1. **Builder stage** - compiles cf-cert-generator with DAP SDK
2. **Runtime stage** - minimal image with only the binary

### Permissions

Runs as current user (`-u $(id -u):$(id -g)`) to avoid permission issues with generated files.

### Volume Mounts

- Host: `tests/stage-env/cache/certs`
- Container: `/output`
- Mounted read-write for certificate output

## Development

### Building Locally

```bash
cd tests/stage-env

# Clean previous certs
./stage-env clean --certs

# Generate new certs (builds Docker image if needed)
./stage-env certs --nodes 10 --validators 5 --force
```

### Debugging

```bash
# Check if image exists
docker images cf-cert-generator

# Run with verbose output
docker run --rm \
  -v $(pwd)/tests/stage-env/cache/certs:/output \
  cf-cert-generator:latest \
  /output 3 stagenet 0x1234

# Check generated files
ls -lR tests/stage-env/cache/certs/
```

### Rebuilding Image

```bash
# Force rebuild image
docker rmi cf-cert-generator:latest

# Next cert generation will rebuild automatically
./stage-env certs
```

## Troubleshooting

### "Docker not found"

**Solution:** Install Docker:
- Linux: `apt install docker.io` or `dnf install docker`
- macOS/Windows: Install Docker Desktop

### "Permission denied" on certificates

**Solution:** Image runs as your user automatically. If issues persist:

```bash
# Fix permissions manually
sudo chown -R $(id -u):$(id -g) tests/stage-env/cache/certs/
```

### "Image build failed"

**Solution:** Check you're in project root with all source files:

```bash
# Must have these directories:
ls dap-sdk/              # DAP SDK source
ls cellframe-sdk/dap-sdk # Cellframe SDK source
ls tests/stage-env/      # Stage-env
```

### "Container exits immediately"

**Solution:** Check command syntax:

```bash
# Correct:
docker run --rm -v $(pwd)/output:/output cf-cert-generator:latest /output 3 stagenet 0x1234

# Wrong (missing arguments):
docker run --rm cf-cert-generator:latest
```

## Platform Notes

### Linux

✅ Works out of the box with Docker installed

### macOS

✅ Works with Docker Desktop  
⚠️ Note: Volume mounts may be slower on macOS

### Windows

✅ Works with Docker Desktop + WSL2  
⚠️ Use WSL2 path format: `/mnt/c/Users/...`

```powershell
# Windows PowerShell
docker run --rm -v ${PWD}/tests/stage-env/cache/certs:/output cf-cert-generator:latest /output 6 stagenet 0x1234
```

## Performance

- **First run**: ~30-60s (build image)
- **Subsequent runs**: ~2-5s (generate certs)
- **Image size**: ~150MB (minimal Debian + binary)

## Integration with CI/CD

### GitHub Actions

```yaml
- name: Generate Certificates
  run: |
    cd tests/stage-env
    ./stage-env certs --nodes 10
    
- name: Upload Certificates
  uses: actions/upload-artifact@v3
  with:
    name: certificates
    path: tests/stage-env/cache/certs/
```

### GitLab CI

```yaml
generate_certs:
  image: docker:latest
  services:
    - docker:dind
  script:
    - cd tests/stage-env
    - ./stage-env certs --nodes 10
  artifacts:
    paths:
      - tests/stage-env/cache/certs/
```

## Advanced Usage

### Custom Network ID

```python
from src.certs.generator import CertGenerator

gen = CertGenerator(base_path)
gen.generate_all(
    network_name="custom-net",
    node_count=10,
    validator_count=7
)
```

### Batch Generation

```bash
# Generate for multiple networks
for net in stagenet testnet devnet; do
  docker run --rm \
    -v $(pwd)/certs-$net:/output \
    cf-cert-generator:latest \
    /output 5 $net 0x$(echo $net | md5sum | cut -c1-4)
done
```

## Security

- ✅ Post-quantum cryptography (Dilithium)
- ✅ Isolated execution in container
- ✅ No privileged access required
- ✅ Deterministic builds

## References

- [DAP SDK Crypto](../../dap-sdk/crypto/)
- [Cellframe Certificate Format](../../docs/certificates.md)
- [Stage-Env Documentation](README.md)

