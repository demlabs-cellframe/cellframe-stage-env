# CLI Retry Mechanism Architecture

## Проблема

После перезапуска контейнеров с Cellframe нодами, CLI команды могут временно возвращать ошибки типа:
- `Can't find state of my node`
- `Connection refused`
- `No such file or directory` (Unix socket ещё не создан)

Это происходит потому что процесс `cellframe-node` внутри контейнера инициализируется не мгновенно после того, как Docker сообщает что контейнер "running".

## Архитектурное решение

### Слои системы

```
┌─────────────────────────────────────────┐
│ YAML Scenario (phase1_zerochain.yml)   │
│  - cli: "node dump"                     │
│  - wait: global_db_sync                 │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ Step Executors (CLI, Wait)              │
│  - CLIStepExecutor                      │
│  - WaitStepExecutor                     │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ ScenarioExecutor._run_cli_command()     │ ◄── RETRY LAYER
│  - retry_on_init_failure                │
│  - max_retries                          │
│  - exponential backoff                  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ DockerContainerManager                  │
│  - exec_cli_command()                   │
│  - Fail-fast crash detection            │
└─────────────────┬───────────────────────┘
                  │
                  ▼
              Docker Exec
```

### Выбранный слой: ScenarioExecutor._run_cli_command()

**Почему именно здесь:**

1. **Не в DockerContainerManager** - этот слой должен быть тупым исполнителем, fail-fast логика для crash detection
2. **Не в CLIStepExecutor** - это специфичный executor для CLI steps, но retry нужен и для waiters
3. **Не в WaitStepExecutor** - waiter'ы используют свой путь через `exec_cli_sync`
4. **✅ В _run_cli_command** - это единая точка входа для ВСЕХ CLI вызовов:
   - CLI steps → CLIStepExecutor → _run_cli_command
   - Waiters → exec_cli_sync → _run_cli_command

### Реализация

```python
async def _run_cli_command(
    self, command: str, node: str, timeout: Optional[int] = 30,
    retry_on_init_failure: bool = False, max_retries: int = 5
) -> Dict[str, Any]:
    """
    Run CLI command with retry logic for initialization failures.
    
    Patterns indicating CLI/node not fully initialized:
    - "Can't find state of my node"
    - "Connection refused"
    - "No such file or directory" (Unix socket not created)
    
    Retry strategy:
    - Exponential backoff: 0.5s → 1s → 2s → 4s → 5s (capped)
    - Max 5 retries (total ~15s)
    - Only retries on init failures, not on real errors
    """
```

### Включение retry

#### Автоматическое (для waiters)

Все waiter'ы автоматически получают retry через `exec_cli_sync`:

```python
def _create_exec_cli_for_waiter(self):
    def exec_cli_sync(node_id: int, command: str, check_output: bool = True) -> tuple:
        result = self._run_cli_command(
            command, f"node{node_id}", 30,
            retry_on_init_failure=True  # ◄── Включено по умолчанию
        )
        return result.get("returncode", -1), result.get("stdout", ""), result.get("stderr", "")
    return exec_cli_sync
```

#### Ручное (для CLI steps, если нужно)

По умолчанию CLI steps НЕ используют retry (fail-fast), но можно добавить если нужно:

```python
result = await self._run_cli_command(
    command, node, timeout,
    retry_on_init_failure=True  # Включить retry вручную
)
```

## Результат

### До изменений

```yaml
- docker_op: restart
  services: "{{all_nodes}}"

- wait_network: online
  nodes: "{{root_nodes}}"

- wait: "5s"  # ◄── Временное решение, не интеллектуальное

- cli: "node dump"  # ◄── Падает: "Can't find state of my node"
  save_node: "root_addr_0"
```

### После изменений

```yaml
- docker_op: restart
  services: "{{all_nodes}}"

- wait_network: online
  nodes: "{{root_nodes}}"

# Больше НЕ нужен wait!
# Retry автоматически обработает "Can't find state" и повторит

- cli: "node dump"  # ◄── Работает, retry внутри
  save_node: "root_addr_0"
```

## Преимущества архитектуры

1. **Единая точка ответственности** - retry логика в одном месте
2. **Прозрачность** - сценарии не меняются, retry "под капотом"
3. **Умное поведение** - различает init failures от реальных ошибок
4. **Fail-fast сохранён** - crash detection работает как прежде
5. **Оптимальный backoff** - экспоненциальная задержка с cap

## Альтернативы (отклонённые)

### ❌ Waiter для CLI readiness

```yaml
- wait: cli_ready
  nodes: "{{root_nodes}}"
```

**Проблема**: Добавляет ~5-10s задержку ДО КАЖДОЙ CLI команды, даже если не нужно.

### ❌ Retry в CLIStepExecutor

**Проблема**: Waiter'ы используют другой путь, нужно дублировать логику.

### ❌ Retry в DockerContainerManager

**Проблема**: Нарушает fail-fast архитектуру для crash detection.

## Итог

Retry механизм реализован на правильном архитектурном слое:
- **Где**: `ScenarioExecutor._run_cli_command()`
- **Как**: Автоматически для waiters, опционально для CLI steps
- **Зачем**: Устранить race condition между "container running" и "CLI ready"
