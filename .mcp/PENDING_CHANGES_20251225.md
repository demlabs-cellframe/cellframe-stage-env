# Pending Changes и Исправления
## Дата: 25 декабря 2025

---

## КРИТИЧЕСКИЕ ИЗМЕНЕНИЯ (уже внесены в test_commands.py)

Эти изменения были внесены для исправления проблемы с переменными топологии:

### Файл: src/cli/test_commands.py

**Изменение 1: Standalone scenarios (строки ~283-310)**

```python
# БЫЛО:
async def _run_standalone():
    await executor.execute_scenario(
        scenario,
        compose_manager=network_mgr.compose if network_mgr else None,
        snapshot_manager=network_mgr.snapshot_manager if network_mgr else None,
        genesis_config_manager=network_mgr.genesis if network_mgr else None,
        node_configs=None  # Will be initialized from running network
    )

# СТАЛО:
# Get node configs and global context from network manager
node_configs = None
global_context = None
if network_mgr:
    node_configs = network_mgr.generate_node_configs()
    # Create global context with node info
    from ..scenarios.global_context import ScenarioGlobalContext
    global_context = ScenarioGlobalContext(
        network_name=network_mgr.topology.network.name,
        topology_name=network_mgr.topology_name
    )
    global_context.set_static_node_info(node_configs)

async def _run_standalone():
    await executor.execute_scenario(
        scenario,
        compose_manager=network_mgr.compose if network_mgr else None,
        snapshot_manager=network_mgr.snapshot_manager if network_mgr else None,
        genesis_config_manager=network_mgr.genesis if network_mgr else None,
        global_context=global_context,
        node_configs=node_configs
    )
```

**Изменение 2: Suite setup (строки ~449-480)**

```python
# БЫЛО:
async def _run_suite_setup():
    await executor.execute_scenario(suite_setup_scenario)

# СТАЛО:
# Get node configs and global context
suite_node_configs = None
suite_global_context = None
if network_mgr:
    suite_node_configs = network_mgr.generate_node_configs()
    from ..scenarios.global_context import ScenarioGlobalContext
    suite_global_context = ScenarioGlobalContext(
        network_name=network_mgr.topology.network.name,
        topology_name=network_mgr.topology_name
    )
    suite_global_context.set_static_node_info(suite_node_configs)

async def _run_suite_setup():
    await executor.execute_scenario(
        suite_setup_scenario,
        compose_manager=network_mgr.compose if network_mgr else None,
        snapshot_manager=network_mgr.snapshot_manager if network_mgr else None,
        genesis_config_manager=network_mgr.genesis if network_mgr else None,
        global_context=suite_global_context,
        node_configs=suite_node_configs
    )
```

**Изменение 3: Suite scenarios (строки ~598-630)**

```python
# БЫЛО:
async def _execute():
    return await executor.execute_scenario(scenario)

# СТАЛО:
# Get node configs and global context
exec_node_configs = None
exec_global_context = None
if network_mgr:
    exec_node_configs = network_mgr.generate_node_configs()
    from ..scenarios.global_context import ScenarioGlobalContext
    exec_global_context = ScenarioGlobalContext(
        network_name=network_mgr.topology.network.name,
        topology_name=network_mgr.topology_name
    )
    exec_global_context.set_static_node_info(exec_node_configs)

async def _execute():
    return await executor.execute_scenario(
        scenario,
        compose_manager=network_mgr.compose if network_mgr else None,
        snapshot_manager=network_mgr.snapshot_manager if network_mgr else None,
        genesis_config_manager=network_mgr.genesis if network_mgr else None,
        global_context=exec_global_context,
        node_configs=exec_node_configs
    )
```

---

## ИЗМЕНЕНИЯ ПОЛЬЗОВАТЕЛЯ (restore_snapshot)

Пользователь добавил поддержку `restore_snapshot` в suite descriptor:

```python
# Clean test data before each suite (if network is running)
if network_mgr:
    # Determine snapshot to restore
    restore_snapshot_name = None
    if isinstance(suite_spec, SuiteDescriptor) and suite_spec.restore_snapshot:
        # Use suite-specific snapshot
        restore_snapshot_name = suite_spec.restore_snapshot
        # Substitute {{topology_name}} if present
        if "{{topology_name}}" in restore_snapshot_name:
            topology_name = getattr(suite_spec.network, 'topology', 'default') if suite_spec.network else 'default'
            restore_snapshot_name = restore_snapshot_name.replace("{{topology_name}}", topology_name)
    
    # OPTIMIZATION: Skip restore for first suite if we have pristine network
    if is_first_suite:
        # ...
        print_success("🚀 Using pristine network (no restore needed)")
    else:
        if restore_snapshot_name:
            print_info(f"🔄 Restoring from snapshot: {restore_snapshot_name}")
        else:
            print_info("🧹 Restoring clean environment state...")
        
        async def _restore_state():
            await network_mgr.restore_clean_state(name=restore_snapshot_name)
        
        try:
            asyncio.run(_restore_state())
            print_success(f"✓ Environment restored from snapshot{': ' + restore_snapshot_name if restore_snapshot_name else ''}")
        except Exception as e:
            print_warning(f"Failed to restore state: {e}")
```

---

## РАНЕЕ ИСПРАВЛЕННЫЕ ПРОБЛЕМЫ

### 1. datum.py - поиск в блоках

```python
# В _check_in_blockchain_blocks():
# Было: искал datum_hash в выводе block list
# Стало: для каждого блока делает block dump и ищет там

for block_hash in block_hashes:
    dump_cmd = [
        self.node_cli_path, "block", "dump",
        "-net", network, "-chain", chain, "-hash", block_hash
    ]
    dump_result = container.exec_run(dump_cmd, demux=True)
    dump_stdout_str = dump_stdout.decode('utf-8') if dump_stdout else ""
    
    if datum_hash.lower() in dump_stdout_str.lower():
        # Found!
```

### 2. wait.py - get_variable

```python
# Было (ошибка - 3 аргумента):
params["network"] = ctx.get_variable('network_name', 'stagenet')

# Стало:
params["network"] = ctx.get_variable('network_name') or 'stagenet'
```

### 3. generator.py - копирование сертификатов

```python
# Добавлено копирование даже если сертификаты существуют:
if self.cert_generator.certs_exist() and not force:
    logger.info("certificates_already_exist_skipping")
    # Still need to copy private certs to node data (may have been cleaned)
    shared_certs_dir = self.configs_cache / "shared" / "ca"
    self.cert_generator.copy_certs_to_shared_ca(shared_certs_dir, network_name)
    self.cert_generator.copy_private_certs_to_node_data(
        self.data_cache,
        node_count,
        network_name
    )
    return
```

### 4. manager.py - emission_hash extraction

```python
# Было: искал event_hash
# Стало: ищет emission_hash в datum секции

emission_datum_match = re.search(
    r'datum:\s*\n\s*datum_type:\s*emission\s*\n\s*emission_hash:\s*(0x[A-Fa-f0-9]{64})', 
    stdout, 
    re.IGNORECASE
)
if emission_datum_match:
    emission_hash = emission_datum_match.group(1)
```

### 5. phase2_esbocs.yml - проверка genesis блока

```python
# Было: просто проверял "have blocks:" в строке
# Стало: парсит число блоков

block_match = re.search(r'have blocks:\s*(\d+)', block_list)
block_count = int(block_match.group(1)) if block_match else 0
has_blocks = block_count > 0
```

---

## ФАЙЛЫ STEP EXECUTORS (созданы/обновлены)

### src/scenarios/step/data.py (НОВЫЙ ФАЙЛ)

```python
"""
Data manipulation step executors (Extract, Count, NodeList, Join, Compute, Format, Assert, Log).
"""

class AssertStepExecutor(StepExecutor):
    async def execute(self, step: AssertStep, ctx: RuntimeContext) -> None:
        condition = step.condition
        substituted_condition = ctx.substitute(condition)
        result = eval(substituted_condition, {"__builtins__": __builtins__}, ctx.variables)
        if not result:
            raise ScenarioExecutionError(step.message or f"Assertion failed: {condition}")

class LogStepExecutor(StepExecutor):
    async def execute(self, step: LogStep, ctx: RuntimeContext) -> None:
        message = ctx.substitute(step.message)
        level = step.level.lower()
        # ... logging based on level

class ExtractStepExecutor(StepExecutor):
    async def execute(self, step: ExtractStep, ctx: RuntimeContext) -> None:
        source = ctx.substitute(step.source)
        match = re.search(step.pattern, source)
        if match:
            ctx.set_variable(step.var_name, match.group(step.group))

class CountStepExecutor(StepExecutor):
    async def execute(self, step: CountStep, ctx: RuntimeContext) -> None:
        source = ctx.substitute(step.source)
        pattern = ctx.substitute(step.pattern)
        count = source.count(pattern)
        ctx.set_variable(step.var_name, count)

class NodeListStepExecutor(StepExecutor):
    def _make_numeric_locals(self, ctx):
        # Convert string vars to numbers for eval
        ...
    
    async def execute(self, step: NodeListStep, ctx: RuntimeContext) -> None:
        # Evaluate start/count expressions
        # Generate node list

class JoinStepExecutor(StepExecutor):
    async def execute(self, step: JoinStep, ctx: RuntimeContext) -> None:
        # Join items or template-generated items

class ComputeStepExecutor(StepExecutor):
    async def execute(self, step: ComputeStep, ctx: RuntimeContext) -> None:
        result = eval(step.expr, safe_builtins, numeric_locals)
        ctx.set_variable(step.var_name, result)

class FormatStepExecutor(StepExecutor):
    async def execute(self, step: FormatStep, ctx: RuntimeContext) -> None:
        result = step.template.format(**format_vars)
        ctx.set_variable(step.var_name, result)
```

### src/scenarios/step/control_flow.py (ОБНОВЛЁН)

Оставлены только:
- `SetStepExecutor`
- `IfStepExecutor`
- `WhileStepExecutor`
- `ForStepExecutor`
- `SwitchStepExecutor`

---

## СХЕМЫ (schema files)

### src/scenarios/schema_data.py (НОВЫЙ ФАЙЛ)

```python
class ExtractStep(BaseModel):
    extract: str = Field(..., alias='var_name')
    source: str
    pattern: str
    group: int = 1
    default: Optional[str] = None

class CountStep(BaseModel):
    count: str = Field(..., alias='var_name')
    source: str
    pattern: str

class NodeListStep(BaseModel):
    node_list: str = Field(..., alias='var_name')
    prefix: str = "node-"
    start: Union[int, str] = 1
    count: Union[int, str]

class JoinStep(BaseModel):
    join: str = Field(..., alias='var_name')
    separator: str = ","
    items: Optional[List[str]] = None
    template: Optional[str] = None
    range_count: Optional[Union[int, str]] = None

class ComputeStep(BaseModel):
    compute: str = Field(..., alias='var_name')
    expr: str

class FormatStep(BaseModel):
    format: str = Field(..., alias='var_name')
    template: str
    # Extra fields allowed for format variables
    model_config = ConfigDict(extra='allow')

class AssertStep(BaseModel):
    assert_: str = Field(..., alias='condition')
    message: Optional[str] = None

class LogStep(BaseModel):
    log: str = Field(..., alias='message')
    level: str = "info"
```

---

## ТЕСТОВЫЕ СЦЕНАРИИ (удалены после успешного тестирования)

Были созданы и удалены после проверки:
- `scenarios/test_new_steps.yml`
- `scenarios/test_compute_format.yml`
- `scenarios/test_data_steps.yml`
- `scenarios/test_check_log.yml`

---

## ТЕКУЩЕЕ СОСТОЯНИЕ ТЕСТИРОВАНИЯ

**Последний запуск genesis phase1:** Прерван (timeout)

**Ожидаемое поведение:**
1. Network стартует
2. Восстанавливается из `primary_phase1_complete` snapshot
3. Инжектируются переменные топологии
4. Выполняется сценарий

**Проблема:** Нужно убедиться что ScenarioGlobalContext правильно создаётся и инжектирует переменные

---

## КОМАНДЫ ДЛЯ ПРОВЕРКИ

```bash
# Запуск genesis phase1
cd /home/cellframe/cellframe-node/tests/stage-env
sudo ./stage-env run-tests --keep-running scenarios/genesis/phase1_zerochain.yml

# Проверка контейнеров
sudo docker ps --format "{{.Names}}: {{.Status}}" | grep cellframe-stage

# Проверка логов
tail -100 /tmp/genesis_phase1_v3.log

# CLI в контейнере
sudo docker exec cellframe-stage-node-1 cellframe-node-cli net get status -net stagenet
```

---

*Документ создан: 25 декабря 2025*

