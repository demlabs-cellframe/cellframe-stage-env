# Changelog — Stage-Env

> [Русская версия](CHANGELOG.ru.md)

## [1.2] — 2026-03-04

### New Features

#### Dynamic Node Provisioning from Suites (`node_compose`, `node_compose_gen`)

Suites can add Cellframe nodes on top of the base topology without manually
editing Docker Compose.

`node_compose` — explicit per-node definitions:

```yaml
node_compose:
  vpn-server-1:
    role: full
    source: genesis         # genesis | node-<id> | fresh
    packages: "iperf3 tcpdump"
    setup:
      - cli: "srv_vpn enable"
        node: vpn-server-1
```

`node_compose_gen` — parametric template-based generation:

```yaml
node_compose_gen:
  - prefix: vpn-client
    count: "{{vpn_client_count}}"
    role: full
    source: genesis
    packages: "iperf3"
```

Expands to `vpn-client-1`, `vpn-client-2`, ...; IDs are assigned automatically
after the last node in the base topology.

#### Arbitrary Docker Services (`docker_compose`)

Embed third-party containers (iperf, redis, grafana, etc.) directly
in the suite descriptor:

```yaml
docker_compose:
  iperf-server:
    image: networkstatic/iperf3
    command: ["-s"]
    networks:
      vpntest:
        ipv4_address: 172.22.0.100
```

#### Flexible Includes with Inline Variable Overrides

`includes` now accepts both file paths and inline data blocks, allowing
variable overrides between file inclusions:

```yaml
includes:
  - ../common/vpn_defaults.yml       # vpn_client_count: 3
  - variables:                        # override
      vpn_client_count: 5
  - ../common/vpn_nodes.yml          # uses 5
```

#### Self-Contained Cert-Generator

Multi-stage `Dockerfile.cert-generator` clones SDK repos at build time.
No host SDK mounts required at runtime — the binary is baked into the image.
Configurable via `SDK_BRANCH`, `CELLFRAME_SDK_REPO`, `DAP_SDK_REPO`.
`CMakeLists.txt` simplified: links against `cellframe_sdk` and `dap-sdk`
shared libs instead of manually listing 15+ static libraries.

#### Glob Patterns for Local Packages

`local_path` in config now supports shell globs (`*.deb`, `build-*/*.deb`).
Picks the latest match (sorted alphabetically) for deterministic results.

#### JSON CLI Output Parsing (SDK 6.0+)

`NodeStateManager` and `DockerComposeManager` parse JSON status format.
Falls back to text format (5.x) on JSON parse failure — compatible
with both SDK 5.x and 6.0+.

#### Auto-Detection of Genesis Scenario Version

The framework detects the Cellframe Node major version from the DEB package
and automatically selects `v5.x/` or `v6.x/` genesis scenarios.
Variables `cf_version_major`, `cf_version_minor` are available at runtime.

#### Dynamic Network Name

Removed hardcoded `stagenet`. `WaitForDatumStep.network` and
`NetworkWaitStep.network` default to `"{{network_name}}"` — the name
is taken from configuration.

#### New `docker_op` Operations

- `pause` / `unpause` — freeze/unfreeze a container to simulate connectivity loss
- `logs` — retrieve logs with `tail:` (line count) and `save:` (into a variable)
- `exec` — execute a command inside a container with `save:`

```yaml
- docker_op: pause
  services: "node-1"

- docker_op: logs
  services: "node-1"
  tail: 50
  save: node_logs

- docker_op: exec
  services: "node-1"
  command: "pgrep cellframe-node"
  save: pid_output
```

#### `snapshot` Extensions

- `verify` operation — checks if a snapshot exists without raising an exception
- `save:` field — stores the result (`True`/`False`) in a variable

```yaml
- snapshot: verify
  name: cdb_ready
  save: has_cdb_snapshot
```

#### `wait` Extensions

- `group:` / `key:` — wait for GlobalDB sync by group/key
- `optional: true` — timeout does not raise an exception (for retry loops)

#### `dpkg` Operand

Install DEB packages on nodes directly from a scenario:

```yaml
- dpkg: /path/to/package.deb
  nodes: ["node-1", "node-2"]
```

#### Custom Operands (`CustomOperandStep`)

Extensible operand system — register new operands via `operand_registry`
without modifying the framework core.

#### `StepGroup`: `group:` / `name:` Alias

Both keys are equivalent for naming a group:

```yaml
- group: "Verify certs"    # OK
- name: "Verify certs"     # also OK
```

#### Regex in `contains`

CLI checks support regular expressions in `contains`:

```yaml
- cli: "block list"
  contains: "have blocks: [1-9]"
```

### Bug Fixes

- **eval() Namespace Unification** — variables and builtins merged into a single
  dict for `eval()`. Expressions like `len(items) == 3` and `range(max_nodes)`
  now work correctly
- **CLI Parser Always Initialized** — defaults applied even without
  `global_defaults.cli`
- **CLI Defaults Applied Without Options Whitelist** — defaults added
  for commands not in the help cache
- `expect_output:` (silently ignored by Pydantic) replaced with `contains:`
  across all genesis/e2e scenarios
- `for: { var: x, in: [...] }` syntax fixed to correct
  `for: x` / `in: [...]`
- `expect:` removed from `check:` sections (CLICheck does not support this field)
- `ToolStep` — added variable substitution for `node` (`ctx.substitute`)
- `Validator` — fixed handling of `SectionConfig`/`CheckSectionConfig`,
  added guard for `SuiteDescriptor`
- CLI check executor — catches `asyncio.TimeoutError` instead of
  `subprocess.TimeoutExpired`
- RPC step — `ctx.substitute()` called only for string parameters
- Bash step — guard against `None` timeout (fallback to 300s)
- Boolean value normalization in configs

### Configuration Templates

Reorganized for multi-version support:

```
config/templates/
├── v5.x/cellframe-node.cfg.j2
├── v6.x/cellframe-node.cfg.j2
├── network.cfg.j2             (formerly stagenet.cfg.j2)
└── chains/
    ├── main.cfg.j2
    └── zerochain.cfg.j2
```

### Documentation

Significantly expanded (EN + RU):

- **02_Language_Constructs** — while loop, for over variables, if with ctx,
  nested groups, helper functions (`join_vars`, `concat`, `get_var`,
  `regex_extract`, `find_all`), special variables
- **03_All_Operands** — `logs`, `exec`, `dpkg`, `pause`/`unpause`, `cp`
- **04_Test_Suites** — node_compose, node_compose_gen, docker_compose,
  inline includes, shared include pattern, debugging suites
- **Glossary / Architecture** — DockerOpStep, StepGroup updated
- Fixed: `snapshot: save` → `create`, `max_iterations` → `max_loops`,
  duplicate TOC entries, broken links

### Testing

- +43 unit tests (58 → 101)
- New modules: `test_core_advanced.py`, `test_custom_operands.py`,
  `test_cli_parser_advanced.py`

### Stats

- **99 files** changed
- **+7,149 / −1,588** lines
- **27 commits**

---

## [1.1] — 2026-01-29

### New Features

#### Print Operand
- `print` step for scenario debugging with Jinja2 templates

```yaml
- print: "Token hash: {{token_hash}}"
```

#### Multi-Node Global DB Sync
- `global_db_sync` supports multiple nodes simultaneously
- Parallel checks instead of sequential — **3x** speedup

#### Block Created Waiter
- `block_created` for monitoring block creation with `min_blocks` parameter

#### Intelligent Waiters in Genesis Scenarios
- Fixed `wait: "Ns"` replaced with intelligent waiting
  with state monitoring

### Bug Fixes

- **CLI Readiness** — retry with exponential backoff on `node dump`
  after `wait_network: online` (up to 10x faster)
- **Config Not Applied After Restart** — `docker_op: restart` replaced with
  `stop` + `start` for correct config reload
- **Global DB Sync Single Node** — all nodes checked instead of only the first
- **is_add_directly** — parameter correctly set in genesis for mainchain
- **MDBX race condition** — workaround before `node dump`

### Performance

| Operation | Before | After |
|-----------|--------|-------|
| Multi-node GDB sync (6 nodes) | 180s | 60s |
| CLI ready wait | 5s fixed | 0.5-5s dynamic |
| Datum processing | 13s fixed | ~3s intelligent |
| Genesis scenarios | ~5 min | ~2 min |

### Documentation

- Full documentation set EN + RU (6 scenario sections,
  Developer Guide, Architecture)
- PDF build system (`docs/build.sh`)

### Testing

- +13 new tests
- Fixed 10 failing tests
- E2E, functional, and regression test frameworks

---

## [1.0] — 2026-01-20

Initial stable release. See git history.
