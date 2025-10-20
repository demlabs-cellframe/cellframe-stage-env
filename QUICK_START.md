# Quick Start Guide

Быстрый старт с Stage Environment за 5 минут.

## ⚡ Минимальный путь

```bash
# 1. Перейдите в директорию
cd tests/stage-env

# 2. Запустите (venv создастся автоматически)
./stage-env start --wait

# 3. Проверьте статус
./stage-env status

# 4. Остановите
./stage-env stop
```

Готово! 🎉

## 📝 Пошаговая инструкция

### Шаг 1: Сборка артефактов

```bash
# Соберите cellframe-node (если ещё не собран)
./stage-env build
```

### Шаг 2: Генерация сертификатов

```bash
# Сгенерируйте сертификаты для нод
./stage-env certs --network stagenet --nodes 4 --validators 3
```

### Шаг 3: Запуск сети

```bash
# Запустите тестовую сеть
./stage-env start --topology default --wait
```

Сеть поднимается примерно за 1-2 минуты.

### Шаг 4: Проверка

```bash
# Посмотрите статус сети
./stage-env status

# Выполните команду в ноде
./stage-env exec node1 "cellframe-node-cli net list"

# Посмотрите логи
./stage-env logs node1 --tail 50
```

### Шаг 5: Запуск тестов

```bash
# Запустите базовые тесты
./stage-env run-tests tests/base

# Или ваши тесты
./stage-env run-tests /path/to/your/tests
```

### Шаг 6: Остановка

```bash
# Остановите сеть
./stage-env stop

# Или с очисткой volumes
./stage-env stop --volumes
```

## 🔧 Частые сценарии

### Чистая пересборка

```bash
./stage-env build --clean
./stage-env certs --force
./stage-env start --clean --wait
```

### Перезапуск конкретной ноды

```bash
./stage-env restart node1
./stage-env logs node1 --follow
```

### Отладка

```bash
# Включите verbose логи
./stage-env --verbose status

# Посмотрите логи контейнера
./stage-env logs node1 --tail 500

# Зайдите в контейнер
./stage-env exec node1 bash
```

### Очистка всего

```bash
./stage-env stop
./stage-env clean --all
```

## 🚨 Troubleshooting

### Ошибка: python3 not found

```bash
# Ubuntu/Debian
sudo apt install python3 python3-venv

# Fedora/RHEL
sudo dnf install python3 python3-virtualenv
```

### Ошибка: docker not found

```bash
# Ubuntu/Debian
sudo apt install docker.io
sudo systemctl start docker
sudo usermod -aG docker $USER
newgrp docker
```

### Ошибка: порты заняты

```bash
# Проверьте какие порты заняты
netstat -tlnp | grep :8080

# Используйте другую топологию
./stage-env start --topology minimal
```

### venv не создаётся

```bash
# Удалите и пересоздайте
rm -rf .venv
./stage-env --help  # Автоматически создаст venv
```

## 📚 Что дальше?

- Прочитайте [README.md](README.md) для полной документации
- Изучите топологии в `config/topologies/`
- Создайте свои тесты
- Настройте CI/CD интеграцию

## 💡 Полезные команды

```bash
# Помощь
./stage-env --help
./stage-env start --help
./stage-env run-tests --help

# Список топологий
ls config/topologies/

# Мониторинг логов
./stage-env logs node1 --follow

# Статус с обновлением
watch -n 2 "./stage-env status"
```
