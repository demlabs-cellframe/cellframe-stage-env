# Stage Environment - Cellframe Node Testing Infrastructure

**Autonomous system for E2E testing of blockchain applications**

Stage Environment is a full-featured infrastructure for running and testing Cellframe Node in an isolated Docker environment. The system is completely autonomous, easily portable, and doesn't require deep programming knowledge to write tests.

## 🎯 Features

- ✅ **YAML Scenarios** - write tests in declarative language without programming
- ✅ **Automation** - build, run, test, collect artifacts
- ✅ **Docker Isolation** - each test in clean environment
- ✅ **Flexible Topologies** - from 1 node to complex networks
- ✅ **Artifacts & Reports** - automatic collection of logs, core dumps, PDF report generation
- ✅ **Rich CLI** - beautiful interface with colored output and progress bars

## 🚀 Quick Start

### Method 1: Using run.sh (Recommended)

The simplest way to run tests is via `run.sh` unified runner:

```bash
cd tests

# Run all tests (E2E + Functional + Regression)
./run.sh

# Run only E2E tests
./run.sh --e2e

# Run only functional tests
./run.sh --functional

# Run specific test suite
./run.sh tests/e2e/token/

# Clean environment and run
./run.sh --clean --e2e
```

**What happens:**
- Automatically starts stage-env network
- Runs selected test suites
- Collects artifacts and generates reports
- Stops network and shows summary

**Results:** `tests/testing/artifacts/run_*/`

### Method 2: Using stage-env directly

For advanced control, use stage-env CLI directly:

```bash
cd tests/stage-env

# 1. Start test network
./stage-env start --wait

# 2. Check status
./stage-env status

# 3. Run tests
./stage-env run-tests ../e2e/

# 4. Stop
./stage-env stop
```

## 📖 Documentation

### For Users & CI/CD

- **[Run.sh Guide](RunShGuide.md)** - Complete guide for running tests with run.sh
- **[Quick Start](#quick-start)** - Get started in 2 minutes

### For QA Engineers

- **[Scenarios Tutorial](scenarios/Tutorial.md)** - Step-by-step learning of scenario language
- **[Scenarios Cookbook](scenarios/Cookbook.md)** - Ready recipes for common tasks
- **[Scenarios Glossary](scenarios/Glossary.md)** - Complete language reference

### For Developers

- **[Architecture](Architecture.md)** - System architecture and internal components
- **Stage-env Code** - Python source in `src/` directory

## 📁 Project Structure

```
stage-env/
├── stage-env                # Bash wrapper (entry point)
├── stage_env.py             # Python CLI (Typer)
├── stage-env.cfg            # Configuration (in tests/)
│
├── src/                     # Python modules
│   ├── scenarios/           # Scenario system (parser, executor, schema)
│   ├── network/             # Network management and topology
│   ├── docker/              # Docker Compose integration
│   ├── config/              # Configuration management
│   ├── certs/               # Certificate generation
│   ├── snapshots/           # Snapshot system (filesystem, squashfs)
│   ├── monitoring/          # Health checks, datum monitoring, artifacts
│   └── utils/               # CLI helpers, logging, reports
│
├── config/                  # Configuration templates
│   ├── topologies/          # Network topology templates
│   └── templates/           # Jinja2 config templates
│       ├── base/            # Base node configs
│       └── chains/          # Blockchain configs
│
├── scenarios/               # YAML test scenarios
│   ├── common/              # Reusable templates
│   ├── genesis/             # Genesis initialization scenarios
│   └── suites/              # Test suites
│
├── tests/                   # Stage-env own tests
│   ├── base/                # Base connectivity tests
│   ├── unit/                # Unit tests for components
│   └── integration/         # Integration tests
│
└── docs/                    # Documentation
    ├── en/                  # English documentation
    │   ├── README.md
    │   ├── RunShGuide.md
    │   ├── Architecture.md
    │   └── scenarios/       # Scenario language docs
    └── ru/                  # Russian documentation
        ├── README.md
        ├── RunShGuide.md
        ├── Architecture.md
        └── scenarios/
```

## 🎨 Main Commands

### via run.sh (Recommended for most users)

```bash
cd tests

# Run tests by type
./run.sh                     # All tests (E2E + Functional + Regression)
./run.sh --e2e               # Only E2E tests
./run.sh --functional        # Only functional tests
./run.sh --regression        # Only regression tests

# Run specific tests
./run.sh tests/e2e/token/    # Run specific test suite
./run.sh tests/e2e/token/001_token_decl.yml  # Run single scenario

# With cleanup/rebuild
./run.sh --clean --e2e       # Clean cache before running
./run.sh --rebuild --e2e     # Rebuild Docker images before running

# Maintenance
./run.sh --stop              # Stop stage environment
./run.sh --pkgs-update       # Update packages in containers
```

### via stage-env CLI (Advanced)

```bash
cd tests/stage-env

# === Network Management ===
./stage-env start --wait         # Start network and wait for ONLINE
./stage-env start --rebuild      # Rebuild images before start
./stage-env stop                 # Stop network
./stage-env stop --volumes       # Stop and remove volumes
./stage-env restart              # Restart all nodes
./stage-env status               # Show node status

# === Testing ===
./stage-env run-tests ../e2e/            # Run tests from directory
./stage-env run-tests ../e2e/test.yml    # Run specific scenario
./stage-env run-tests --filter token     # Filter by name

# === Monitoring ===
./stage-env logs node-1              # Show node logs (last 100 lines)
./stage-env logs node-1 --follow     # Follow logs in real-time
./stage-env exec node-1 "ls -la"     # Execute command in node

# === Certificates ===
./stage-env certs                    # Generate certificates (default topology)
./stage-env certs --force            # Regenerate existing

# === Snapshots ===
./stage-env snapshots-list           # List snapshots
./stage-env snapshots-delete <hash>  # Delete specific snapshot
./stage-env snapshots-info <hash>    # Show snapshot details
./stage-env snapshots-clean          # Clean old snapshots

# === Build & Rebuild ===
./stage-env build                    # Build cellframe-node
./stage-env rebuild                  # Rebuild images and restart

# === Cleanup ===
./stage-env clean --all              # Clean everything
./stage-env pkgs-update              # Update packages in containers
```

## 📝 Writing Tests

### Simple Test

```yaml
# scenarios/my_test.yml
name: My First Test
description: Check wallet creation

includes:
  - common/network_minimal.yml

test:
  - cli: wallet new -w test_wallet
    save: wallet_addr
  
  - cli: wallet list
    contains: test_wallet

check:
  - cli: wallet info -w test_wallet
    contains: {{wallet_addr}}
```

### Running Scenario

```bash
cd tests/stage-env
./stage-env run-tests ../e2e/my_test.yml
```

**Or via run.sh:**
```bash
cd tests
./run.sh tests/e2e/my_test.yml
```

### Ready Templates

- `scenarios/common/network_minimal.yml` - Minimal network (1 node)
- `scenarios/common/network_full.yml` - Full network (multiple nodes)
- `scenarios/common/wallet_setup.yml` - Pre-configured wallet
- `scenarios/common/set_net_default.yml` - Auto-add -net parameter

## 🔧 Configuration

Main configuration in `tests/stage-env.cfg`:

```ini
# === Network ===
[network]
name = stagenet                    # Network name
network_id = 0x1234                # Network ID
consensus_type = esbocs            # Consensus type (esbocs/pos/poa)

# === Topology ===
[topology]
root_nodes_count = 3               # Number of root nodes
master_nodes_count = 3             # Number of master nodes
full_nodes_count = 1               # Number of full nodes

# === Build ===
[build]
build_type = debug                 # debug or release
cellframe_version = latest         # Cellframe Node version

# === Network Settings ===
[network_settings]
base_rpc_port = 8545               # Base RPC port
base_p2p_port = 31337              # Base P2P port
base_http_port = 8079              # Base HTTP port
node_port = 8079                   # External connection port
subnet = 172.20.0.0/16             # Docker subnet

# === Consensus ===
[consensus]
min_validators = 2                 # Minimum validators
new_round_delay = 45               # Delay between rounds
collecting_level = 10.0            # Voting collection level
auth_certs_prefix = stagenet.master # Certificate prefix

# === Balancer ===
[balancer]
enabled = true                     # Enable balancer
type = http                        # Balancer type (http)
uri = f0intlt4eyl03htogu           # Balancer URI
max_links_response = 10            # Max links in response
request_delay = 20                 # Delay between requests

# === Features ===
[features]
monitoring = false                 # Monitoring
tests = false                      # Test mode
crash_artifacts = true             # Collect crash artifacts

# === Paths ===
[paths]
cache_dir = ../testing/cache       # Cache directory
artifacts_dir = ../testing/artifacts # Artifacts directory

# === Logging ===
[logging]
log_dir = ../testing/logs          # Log directory
log_level = info                   # Log level (debug/info/warning/error)
scenario_logs = true               # Log scenario execution
retain_days = 7                    # Keep logs for N days

# === Artifacts ===
[artifacts]
collect_node_logs = true           # Collect node logs
collect_health_logs = true         # Collect health check logs
collect_crash_dumps = true         # Collect core dumps
retain_days = 30                   # Keep artifacts for N days

# === Timeouts (in seconds) ===
[timeouts]
startup = 600                      # Network startup timeout
health_check = 600                 # Health check timeout
command = 30                       # Command execution timeout

# === Node Source ===
[node_source]
type = local                       # local/url/repository
local_path = ../test_build/cellframe-node.deb  # Path to local .deb
# url = https://...                # URL for download
# repository_url = https://...     # Git repository for build
```

## 🎯 Integration into Your Project

### Using run.sh (Recommended)

```bash
#!/bin/bash
# Simple wrapper for your project

cd tests
./run.sh --e2e
```

### Using stage-env directly

```bash
#!/bin/bash
set -euo pipefail

cd tests/stage-env

# Start network
./stage-env start --wait

# Run tests
./stage-env run-tests ../e2e/

# Stop
./stage-env stop
```

### Topology Configuration

Create `config/topologies/my-network.json`:

```json
{
  "network": {
    "name": "mynet",
    "network_id": "0x5678"
  },
  "topology": {
    "validators": {
      "count": 5,
      "role": "validator",
      "consensus_participation": true
    },
    "full_nodes": {
      "count": 2,
      "role": "full",
      "consensus_participation": false
    }
  }
}
```

Run:

```bash
./stage-env start --topology my-network
```

## 📊 Artifacts and Reports

After each run in `testing/artifacts/<run_id>/`:

```
e2e_20251023_150000/
├── reports/
│   ├── report.md            # Markdown report
│   └── report.pdf           # PDF report (pandoc)
├── stage-env-logs/          # Stage-env logs
├── node-logs/               # Docker container logs
├── core-dumps/              # Core dumps (if any)
├── health-logs/             # Health check logs
└── summary.json             # JSON summary
```

## 🔍 Troubleshooting

### Docker Issues

```bash
# Check Docker
docker ps
docker compose version

# Restart Docker
sudo systemctl restart docker
```

### Port Issues

```bash
# Check occupied ports
ss -tlnp | grep 8079

# Stop via run.sh
cd tests
./run.sh --stop

# Or directly
cd tests/stage-env
./stage-env stop --volumes
```

### Python Issues

```bash
cd tests/stage-env

# Recreate venv
rm -rf .venv
./stage-env --help  # Will create venv automatically
```

### Debug Logs

```bash
cd tests/stage-env

# Verbose mode
./stage-env --verbose start

# Specific node logs
./stage-env logs node-1 --tail 100

# Follow logs in real-time
./stage-env logs node-1 --follow

# All nodes status
./stage-env status
```

## 📚 Detailed Documentation

- **[Tutorial](scenarios/Tutorial.md)** - Step-by-step guide for QA
- **[Cookbook](scenarios/Cookbook.md)** - Recipes for common tasks
- **[Glossary](scenarios/Glossary.md)** - Complete language reference

## 🤝 Contributing

1. Fork repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Create Pull Request

## 📜 License

See LICENSE in project root.

## 🔗 Links

- [Cellframe Node](https://github.com/demlabs-cellframe/cellframe-node)
- [DAP SDK](https://github.com/demlabs-cellframe/dap-sdk)
- [Python Cellframe](https://github.com/demlabs-cellframe/python-cellframe)

---

**Language:** English | [Русский](../ru/README.md)

