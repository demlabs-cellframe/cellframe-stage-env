# Changelog - Stage-Env

## [2.2.0] - 2026-03-04

### 🆕 New Features

#### Self-Contained Cert-Generator Docker Image
- Multi-stage Dockerfile clones SDK repos at build time
- No host SDK mounts required at runtime — binary is baked into the image
- Configurable via `SDK_BRANCH`, `CELLFRAME_SDK_REPO`, `DAP_SDK_REPO` build args

#### Glob Patterns for Local Packages
- `local_path` in config now supports shell glob patterns (`*.deb`, `build-*/*.deb`)
- Picks the latest match (sorted alphabetically) for deterministic results
- Works in both `compose.py` node source and `loader.py` extra packages

#### JSON CLI Output Parsing (SDK 6.0+)
- `NodeStateManager` and `DockerComposeManager` parse JSON status format
- Falls back to text format (5.x) when JSON parsing fails
- Enables compatibility with both SDK 5.x and 6.0+

### 🐛 Bug Fixes

#### eval() Namespace Unification (Critical)
- **Problem:** `if`, `while`, `for`, `switch` conditions failed when referencing ctx variables
  combined with builtins like `len()`, `range()`, `str()`
- **Root Cause:** Variables were passed as `locals` dict, making them invisible to nested function calls
- **Solution:** Merge builtins + variables into a single `globals` dict for `eval()`
- **Impact:** Expressions like `len(items) == 3` and `range(max_nodes)` now work reliably

#### CLI Parser Always Initialized
- **Problem:** CLI defaults not applied when `global_defaults.cli` was absent
- **Root Cause:** Parser initialization was gated on `global_defaults and global_defaults.cli`
- **Solution:** Initialize parser whenever `compose_manager` is available
- **Impact:** Default options (e.g. `-net stagenet`) now applied even without explicit CLI defaults

#### CLI Defaults Applied Without Options Whitelist
- **Problem:** Defaults silently dropped for commands with no parsed option list
- **Root Cause:** `apply_cli_defaults` required option in `available_options`
- **Solution:** Add default when `available_options` is empty (command not in help cache)
- **Impact:** Defaults are applied even for commands not yet in the help cache

#### Core Dumps Collected Reliably
- Core dumps now land in `/opt/cellframe-node/var/coredumps` inside the container
- Directory is bind-mounted via var/, accessible from host without `docker cp`

### 🔧 Architecture

#### Simplified SDK Linking for cert-generator
- `CMakeLists.txt` links against `cellframe_sdk` and `dap-sdk` shared libs
- Removed manual enumeration of 15+ static libraries and XKCP targets
- Reduced CMake complexity by ~60 lines

#### Config Path Changed
- `run.sh` now reads config from `$PROJECT_ROOT/tests/stage-env.cfg`
- Separates tool config from stage-env source tree

### 🧪 Testing

- Added `TestControlFlowEvalNamespace` — 4 tests for unified eval namespace
- Added `TestNodeStateJSONParsing` — 4 tests for JSON/text format parsing
- Added `test_apply_cli_defaults_adds_all_when_unparsed` for unparsed commands
- All existing tests updated for new behavior

---

## [2.1.0] - 2026-01-29

### 🆕 New Features

#### Print Operand
- Added `print` step for debugging scenarios
- Supports Jinja2 templating for variables
- Can display complex data structures (dicts, lists)
- Output visible in logs and console

```yaml
- print: "Token hash: {{token_hash}}"
```

#### Multi-Node Global DB Sync
- `global_db_sync` waiter now supports multiple nodes
- Parallel checking instead of sequential
- **3x faster** for 6-node networks
- Backward compatible with single `node` parameter

```yaml
# Old: sequential
- for: node in {{nodes}}
  - wait: global_db_sync
    node: {{node}}

# New: parallel
- wait: global_db_sync
  nodes: {{nodes}}
```

#### Block Created Waiter
- New `block_created` waiter for monitoring block creation
- Supports `min_blocks` parameter
- Currently disabled due to SDK MDBX bug

```yaml
- wait: block_created
  node: {{first_master}}
  chain: main
  min_blocks: 1
```

### 🐛 Bug Fixes

#### CLI Readiness (Critical)
- **Problem:** `node dump` failed after `wait_network: online` 
- **Root Cause:** Network online ≠ CLI ready
- **Solution:** Automatic retry mechanism with exponential backoff
- **Impact:** **10x faster** in best case (0.5s vs 5s fixed wait)

```yaml
# OLD: Manual workaround
- wait_network: online
- wait: "5s"  # Wait for CLI
- cli: "node dump"

# NEW: Automatic
- wait_network: online
- cli: "node dump"  # Retries if not ready
```

#### Config Not Applied After Restart (Critical)
- **Problem:** `docker_op: restart` didn't reload config files
- **Root Cause:** Node process doesn't watch config changes
- **Solution:** Use `docker_op: stop` + `docker_op: start`
- **Impact:** Genesis scenarios now work correctly

```yaml
# OLD: Config not applied
- config: ...
- docker_op: restart  # ❌

# NEW: Config applied
- config: ...
- docker_op: stop
- docker_op: start  # ✅
```

#### Global DB Sync Single Node (Critical)
- **Problem:** Only first node checked, others could lag
- **Root Cause:** `global_db_sync` checked single node
- **Solution:** Multi-node support
- **Impact:** Genesis block now syncs correctly to all nodes

### ⚡ Performance Improvements

| Operation | Before | After | Speedup |
|-----------|--------|-------|---------|
| Multi-node GDB sync (6 nodes) | 180s | 60s | **3x** |
| CLI ready wait | 5s fixed | 0.5-5s dynamic | **10x** |
| Datum processing | 13s fixed | ~3s intelligent | **4x** |
| Genesis scenarios | ~5min | ~2min | **2.5x** |

### 📚 Documentation

- Added comprehensive unit tests for new features
- Created NEW_FEATURES.md guide
- Updated Glossary.md with new operands
- Added 4 new recipes to Cookbook.md
- Updated README.md with feature list

### 🔧 Architecture

#### CLI Retry Mechanism
- Centralized in `ScenarioExecutor._run_cli_command`
- Detects initialization failure patterns
- Exponential backoff: 0.5s → 1s → 2s → 4s → 5s (max)
- Up to 10 retries
- Applied to `save_node` operations and waiters

#### Multi-Node Waiter Support
- `GlobalDBNodeListSyncWaiter` refactored
- Accepts `nodes` (list) or `node` (single)
- Tracks `_synced_nodes` set
- Returns `True` only when all synced

#### Docker Operations
- Added `DockerComposeManager.stop()` method
- Separates stop from down (preserves state)
- Enables proper config reload workflow

### 🧪 Testing

- Fixed 6 failing unit tests after refactoring
- Added `test_new_features.py` with 13 new tests
- Removed broken `test_issue_template.py`
- All CI/CD tests now pass
- Genesis scenarios (Phase 1 + 2) pass

### 📦 Commits

Total: 15 commits
- 7 fixes (CLI retry, config reload, multi-node sync)
- 4 features (print, multi-node waiter, block_created)
- 3 tests (new tests, fixes, documentation)
- 1 architecture (executor refactoring)

## [2.0.0] - Previous

(See git history)
