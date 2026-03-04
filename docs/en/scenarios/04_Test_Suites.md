# Test Suites

## Suite Structure

```yaml
# suite_setup.yml
suite_name: Token Tests
suite_description: Comprehensive token testing

suite_setup:
  variables:
    network_name: stagenet
    native_ticker: TCELL
    
  steps:
    - cli: "wallet new -w shared_wallet"
      save_wallet: suite_wallet
    # Available in all scenarios

scenarios:
  - token/001_token_decl.yml
  - token/002_token_emit.yml
```

## Suite Variables

### Definition
```yaml
suite_setup:
  variables:
    shared_var: value
```

### Usage in Scenarios
```yaml
# Any scenario in suite
test:
  - cli: "wallet info -w {{suite_wallet}}"
  - print: "API: {{api_key}}"
```

### Visibility
- Available in all scenarios within the suite
- Cannot be overridden by individual scenarios
- Take priority over global variables

## Suite Lifecycle

1. Parse suite_setup.yml
2. Execute suite_setup steps
3. Save suite variables
4. For each scenario:
   - Load scenario
   - Merge suite variables
   - Execute scenario
   - Collect results
5. Generate suite report

## Suite Configuration

### Network Topology
```yaml
suite_setup:
  network:
    topology: custom
    root_nodes: 3
    master_nodes: 3
```

### Packages
```yaml
suite_setup:
  packages:
    - name: vim
      nodes: all
```

### Files
```yaml
suite_setup:
  files:
    - src: config.txt
      dst: /opt/config.txt
      nodes: all
    - src: script.sh
      dst: /tmp/script.sh
      nodes: [node1]
      mode: "755"
```

## Advanced Patterns

### Shared Setup
```yaml
suite_setup:
  steps:
    - for: i
      in: "range(5)"
      eval: true
      steps:
        - cli: "wallet new -w wallet{{i}}"
          save_wallet: "wallet{{i}}_addr"
```

### Shared Resources
```yaml
suite_setup:
  variables:
    shared_token: MYTOKEN

  steps:
    - cli: "token_decl -t {{shared_token}}"
      save_hash: token_hash
    - cli: "token_emit -t {{shared_token}}"
      save_hash: emission_hash
```

### Conditional Setup
```yaml
suite_setup:
  steps:
    - if: "{{ctx.has_variable('ENABLE_FEATURE_X')}}"
      then:
        - cli: "enable feature_x"
```

## E2E Suite Descriptors

E2E test suites use a lightweight descriptor format with `suite:` field.

### Directory Layout

Two patterns are supported:

```
# Pattern A: External descriptor
tests/e2e/cdb/
├── kelvpn.yml            ← descriptor next to directory
└── kelvpn/
    ├── test_connect.yml
    └── test_auth.yml

# Pattern B: Internal descriptor
tests/e2e/cdb/
└── kelvpn/
    ├── suite.yml          ← descriptor inside directory
    ├── test_connect.yml
    └── test_auth.yml
```

### Descriptor Format

```yaml
suite: "KelVPN Client E2E Tests"
description: "Tests for KelVPN client"
tags: [e2e, kelvpn]

network:
  topology: default

variables:
  serial_count: 5
  cdb_endpoint: "http://node9:8079"

scenarios:
  - test_connect.yml
  - test_auth.yml

includes:
  - common/cdb-plugin-setup.yml

setup:
  - cli: "vpn_cdb version"
    node: node9
```

### Includes — File Paths and Inline Data

The `includes` list accepts both **file paths** (strings) and **inline data blocks** (dicts). Entries are processed in declared order, which enables variable overrides between file includes:

```yaml
includes:
  - ../common/vpn_defaults.yml       # sets vpn_client_count: 3
  - variables: { vpn_client_count: 5 }  # override before next include
  - ../common/vpn_nodes.yml          # uses vpn_client_count = 5
  - ../common/vpn_service_setup.yml
```

Inline blocks may contain any keys supported by included YAML files: `variables`, `node_compose`, `node_compose_gen`, `defaults`, etc.

### Variable Inheritance Priority

1. Topology variables (IPs, network name) — highest
2. Scenario `variables:` section
3. Suite descriptor `variables:` section — lowest (defaults)

Includes are processed in order. Each include's `variables` are merged underneath the suite's own `variables` (suite values take priority). This means earlier includes set defaults that later includes or the suite itself can override.

---

## Dynamic Node Provisioning

Suites can dynamically add Cellframe nodes beyond the base topology using `node_compose` and `node_compose_gen`.

### node_compose — Explicit Node Definitions

Define individual nodes as a dictionary where keys are Docker Compose service names:

```yaml
node_compose:
  vpn-server-1:
    id: 9                   # optional — auto-assigned if omitted
    role: full              # root | master | full (default: full)
    source: genesis         # genesis | node-<id> | fresh (default: genesis)
    packages: "iperf3 tcpdump"  # space-separated deb packages
    config_overrides:       # optional config tweaks
      server:
        enabled: true
    setup:                  # optional per-node setup steps
      - cli: "srv_vpn enable"
        node: vpn-server-1

  vpn-client-1:
    source: genesis
    packages: "iperf3"
```

**Source modes:**
- `genesis` — restore from the suite's base genesis snapshot (default)
- `node-N` — clone configs and data from existing node N
- `fresh` — empty dirs with only a base `cellframe-node.cfg`

### node_compose_gen — Parametric Generation

Generate multiple nodes from a template using a prefix and count:

```yaml
node_compose_gen:
  - prefix: vpn-server
    count: "{{vpn_server_count}}"   # int or {{variable}} reference
    role: full
    source: genesis
    packages: "iperf3 tcpdump"

  - prefix: vpn-client
    count: "{{vpn_client_count}}"
    role: full
    source: genesis
    packages: "iperf3"
```

This expands into `vpn-server-1`, `vpn-server-2`, ..., `vpn-client-1`, `vpn-client-2`, etc. IDs are auto-assigned sequentially after the last base topology node.

### Shared Include Pattern

Define default counts and node generators in reusable includes:

```yaml
# common/vpn_defaults.yml
variables:
  vpn_server_count: 2
  vpn_client_count: 3
```

```yaml
# common/vpn_nodes.yml
node_compose_gen:
  - prefix: vpn-server
    count: "{{vpn_server_count}}"
    role: full
    source: genesis
    packages: "iperf3 tcpdump"
  - prefix: vpn-client
    count: "{{vpn_client_count}}"
    role: full
    source: genesis
    packages: "iperf3"
```

```yaml
# stress/suite.yml
includes:
  - ../common/vpn_defaults.yml
  - variables: { vpn_client_count: 5 }  # override for this suite
  - ../common/vpn_nodes.yml
```

---

## docker_compose — Additional Services

Merge arbitrary Docker Compose service definitions into the generated `docker-compose.yml`:

```yaml
docker_compose:
  iperf-server:
    image: networkstatic/iperf3
    command: ["-s"]
    restart: "no"
    networks:
      vpntest:
        ipv4_address: 172.22.0.100

  redis:
    image: redis:7-alpine
    networks:
      vpntest:
```

Services defined here are merged directly into the Docker Compose file. The network name must match `[network].name` from `stage-env.cfg`.

A special `packages` field can be added to Cellframe node services — it is stripped before the Compose merge and the listed deb packages are installed on all Cellframe nodes at startup:

```yaml
docker_compose:
  monitoring:
    image: grafana/grafana
    packages: "prometheus-node-exporter"  # installed on all cf nodes
    networks:
      vpntest:
```

---

## Complete Stress Suite Example

```yaml
suite: VPN Stress Tests
description: >
  Comprehensive stress test suite: multi-client load, blockchain load,
  multihop, multi-uplink failover, traffic obfuscation, and network faults.
tags: [stress, vpn, load, e2e]

restore_snapshot: vpn_stress_state

includes:
  - ../common/vpn_defaults.yml
  # Override counts: - variables: { vpn_client_count: 5 }
  - ../common/vpn_nodes.yml
  - ../common/vpn_service_setup.yml
  - ../common/fault_injection_helpers.yml

variables:
  iperf_duration: 120
  iperf_parallel: 4

docker_compose:
  iperf-server:
    image: networkstatic/iperf3
    command: ["-s"]
    restart: "no"
    networks:
      vpntest:
        ipv4_address: 172.22.0.100

scenarios:
  - test_multi_client_load.yml
  - test_blockchain_load.yml
  - test_multihop.yml
  - test_multi_uplink.yml
  - test_obfuscation.yml
  - test_network_faults.yml
```

---

## Best Practices

1. **Share common setup in suite** — create resources once
2. **Use suite variables** — for shared data
3. **Keep scenarios independent** — don't rely on execution order
4. **Use meaningful suite names** — descriptive names for `suite:` field
5. **Separate defaults and generators** — use `vpn_defaults.yml` + `vpn_nodes.yml` pattern
6. **Use inline variable overrides** — to customize shared includes per-suite
7. **Prefer node_compose_gen** — over manual node_compose for repetitive nodes

## Debugging Suites

### Running a Single Scenario
```bash
./stage-env start --scenario genesis/phase1_zerochain.yml
```

### Skipping Suite Setup
```bash
./stage-env start --skip-suite-setup
```

### Inspecting Variables
```yaml
# In any scenario
test:
  - python: |
      print("Suite variables:")
      for k, v in ctx.variables.items():
          if not k.startswith('_'):
              print(f"  {k}: {v}")
```
