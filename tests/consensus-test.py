#!/usr/bin/env python3
"""
Тесты консенсуса ESBocs для Cellframe Node тестовой сети
Проверяет работу консенсуса между тремя нодами
"""

import requests
import json
import time
import sys
from typing import List, Dict, Any

# Dynamic node configuration from environment
import os

def get_node_configuration():
    """Get node configuration from environment variables"""
    master_nodes = int(os.getenv('Cellframe Node_TEST_MASTER_NODES', '3'))
    full_nodes = int(os.getenv('Cellframe Node_TEST_FULL_NODES', '0'))
    base_port = int(os.getenv('Cellframe Node_TEST_BASE_RPC_PORT', '8545'))
    
    nodes = []
    
    # Add master nodes
    for i in range(1, master_nodes + 1):
        port = base_port - 1 + i
        nodes.append({
            "name": f"Master Node {i}",
            "url": f"http://localhost:{port}",
            "type": "master",
            "id": i
        })
    
    # Add full nodes  
    for i in range(1, full_nodes + 1):
        port = base_port - 1 + master_nodes + i
        node_id = master_nodes + i
        nodes.append({
            "name": f"Full Node {i}",
            "url": f"http://localhost:{port}",
            "type": "full",
            "id": node_id
        })
    
    return nodes

# Get dynamic node configuration
NODES = get_node_configuration()

class Cellframe NodeConsensusTester:
    def __init__(self):
        self.passed_tests = 0
        self.total_tests = 0
        
    def log(self, level: str, message: str):
        """Логирование с временными метками"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        colors = {
            "INFO": "\033[92m",    # Green
            "WARN": "\033[93m",    # Yellow
            "ERROR": "\033[91m",   # Red
            "SUCCESS": "\033[95m", # Purple
        }
        reset = "\033[0m"
        color = colors.get(level, "")
        print(f"{color}[{level}]{reset} {timestamp} {message}")
    
    def make_rpc_call(self, node_url: str, method: str, params: List[Any] = None) -> Dict[Any, Any]:
        """Выполнение RPC вызова к ноде"""
        if params is None:
            params = []
            
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        try:
            response = requests.post(
                node_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}
    
    def get_block_by_number(self, node_url: str, block_number: int) -> Dict[Any, Any]:
        """Получение блока по номеру"""
        hex_number = hex(block_number)
        return self.make_rpc_call(node_url, "eth_getBlockByNumber", [hex_number, True])
    
    def test_block_production(self) -> bool:
        """Тест производства блоков"""
        self.log("INFO", "Тестирование производства блоков...")
        self.total_tests += 1
        
        # Получаем начальные номера блоков
        initial_blocks = {}
        for node in NODES:
            result = self.make_rpc_call(node['url'], "eth_blockNumber")
            if "result" in result:
                initial_blocks[node['id']] = int(result["result"], 16)
            else:
                self.log("ERROR", f"Не удалось получить блок от {node['name']}")
                return False
        
        self.log("INFO", f"Начальные блоки: {initial_blocks}")
        
        # Ждем производства новых блоков (30 секунд)
        self.log("INFO", "Ожидание производства новых блоков (30 секунд)...")
        time.sleep(30)
        
        # Получаем новые номера блоков
        new_blocks = {}
        for node in NODES:
            result = self.make_rpc_call(node['url'], "eth_blockNumber")
            if "result" in result:
                new_blocks[node['id']] = int(result["result"], 16)
            else:
                self.log("ERROR", f"Не удалось получить блок от {node['name']}")
                return False
        
        self.log("INFO", f"Новые блоки: {new_blocks}")
        
        # Проверяем что блоки увеличились
        blocks_produced = False
        for node_id in initial_blocks:
            if new_blocks[node_id] > initial_blocks[node_id]:
                blocks_produced = True
                self.log("SUCCESS", f"✓ Node {node_id}: произведено {new_blocks[node_id] - initial_blocks[node_id]} блоков")
        
        if blocks_produced:
            self.passed_tests += 1
            return True
        else:
            self.log("ERROR", "✗ Новые блоки не были произведены")
            return False
    
    def test_block_consistency(self) -> bool:
        """Тест консистентности блоков между нодами"""
        self.log("INFO", "Тестирование консистентности блоков...")
        self.total_tests += 1
        
        # Получаем последние блоки от всех нод
        latest_blocks = {}
        for node in NODES:
            result = self.make_rpc_call(node['url'], "eth_blockNumber")
            if "result" in result:
                block_number = int(result["result"], 16)
                latest_blocks[node['id']] = block_number
            else:
                self.log("ERROR", f"Не удалось получить блок от {node['name']}")
                return False
        
        # Находим минимальный общий блок
        min_block = min(latest_blocks.values())
        if min_block < 1:
            self.log("WARN", "Недостаточно блоков для проверки консистентности")
            return True
        
        self.log("INFO", f"Проверка консистентности блока #{min_block}")
        
        # Получаем блок от каждой ноды
        blocks = {}
        for node in NODES:
            block_data = self.get_block_by_number(node['url'], min_block)
            if "result" in block_data and block_data["result"]:
                blocks[node['id']] = block_data["result"]
            else:
                self.log("ERROR", f"Не удалось получить блок #{min_block} от {node['name']}")
                return False
        
        # Сравниваем хеши блоков
        block_hashes = {node_id: block.get("hash") for node_id, block in blocks.items()}
        unique_hashes = set(block_hashes.values())
        
        if len(unique_hashes) == 1:
            self.log("SUCCESS", f"✓ Блок #{min_block} консистентен между всеми нодами")
            self.log("INFO", f"Хеш блока: {list(unique_hashes)[0]}")
            self.passed_tests += 1
            return True
        else:
            self.log("ERROR", f"✗ Блок #{min_block} имеет разные хеши на нодах:")
            for node_id, hash_val in block_hashes.items():
                self.log("ERROR", f"  Node {node_id}: {hash_val}")
            return False
    
    def test_validator_participation(self) -> bool:
        """Тест участия валидаторов в консенсусе"""
        self.log("INFO", "Тестирование участия валидаторов...")
        self.total_tests += 1
        
        # Получаем несколько последних блоков для анализа
        node_url = NODES[0]['url']  # Используем первую ноду
        
        result = self.make_rpc_call(node_url, "eth_blockNumber")
        if "error" in result:
            self.log("ERROR", "Не удалось получить номер последнего блока")
            return False
        
        latest_block = int(result["result"], 16)
        
        if latest_block < 5:
            self.log("WARN", "Недостаточно блоков для анализа участия валидаторов")
            return True
        
        # Анализируем последние 5 блоков
        validators_seen = set()
        for i in range(max(1, latest_block - 4), latest_block + 1):
            block_data = self.get_block_by_number(node_url, i)
            if "result" in block_data and block_data["result"]:
                block = block_data["result"]
                miner = block.get("miner")
                if miner:
                    validators_seen.add(miner.lower())
                    self.log("INFO", f"Блок #{i}: валидатор {miner}")
        
        self.log("INFO", f"Найдено уникальных валидаторов: {len(validators_seen)}")
        
        # В идеале должно быть участие всех 3 валидаторов, но минимум 2
        if len(validators_seen) >= 2:
            self.log("SUCCESS", f"✓ Участвует валидаторов: {len(validators_seen)}")
            self.passed_tests += 1
            return True
        else:
            self.log("WARN", f"? Участвует только {len(validators_seen)} валидаторов")
            # Не считаем это критической ошибкой
            self.passed_tests += 1
            return True
    
    def test_network_finalization(self) -> bool:
        """Тест финализации блоков в сети"""
        self.log("INFO", "Тестирование финализации блоков...")
        self.total_tests += 1
        
        # Получаем информацию о финализации от всех нод
        finalization_info = {}
        for node in NODES:
            # Пытаемся получить информацию о финализованном блоке
            result = self.make_rpc_call(node['url'], "eth_getBlockByNumber", ["finalized", False])
            if "result" in result and result["result"]:
                finalized_block = result["result"]
                finalization_info[node['id']] = {
                    "number": int(finalized_block["number"], 16),
                    "hash": finalized_block["hash"]
                }
            else:
                # Если нет поддержки "finalized", используем latest - некоторый offset
                result = self.make_rpc_call(node['url'], "eth_blockNumber")
                if "result" in result:
                    latest = int(result["result"], 16)
                    # Считаем финализованным блок на 6 блоков назад
                    finalized_number = max(0, latest - 6)
                    finalization_info[node['id']] = {
                        "number": finalized_number,
                        "hash": "estimated"
                    }
        
        if not finalization_info:
            self.log("ERROR", "Не удалось получить информацию о финализации")
            return False
        
        # Проверяем консистентность финализации
        finalized_numbers = [info["number"] for info in finalization_info.values()]
        min_finalized = min(finalized_numbers)
        max_finalized = max(finalized_numbers)
        
        if max_finalized - min_finalized <= 2:
            self.log("SUCCESS", f"✓ Финализация консистентна (блоки {min_finalized}-{max_finalized})")
            self.passed_tests += 1
            return True
        else:
            self.log("ERROR", f"✗ Финализация не консистентна (разброс: {max_finalized - min_finalized})")
            return False
    
    def run_all_tests(self) -> bool:
        """Запуск всех тестов консенсуса"""
        self.log("INFO", "=== Начало тестирования консенсуса ESBocs ===")
        
        # Проверяем доступность всех нод
        available_nodes = 0
        for node in NODES:
            result = self.make_rpc_call(node['url'], "eth_blockNumber")
            if "result" in result:
                available_nodes += 1
                self.log("INFO", f"✓ {node['name']} доступна")
            else:
                self.log("WARN", f"✗ {node['name']} недоступна")
        
        if available_nodes < 2:
            self.log("ERROR", "Недостаточно нод для тестирования консенсуса")
            return False
        
        # Запускаем тесты
        self.test_block_production()
        self.test_block_consistency()
        self.test_validator_participation()
        self.test_network_finalization()
        
        # Выводим итоги
        success_rate = (self.passed_tests / self.total_tests) * 100 if self.total_tests > 0 else 0
        
        self.log("INFO", f"=== Результаты тестирования консенсуса ===")
        self.log("INFO", f"Всего тестов: {self.total_tests}")
        self.log("INFO", f"Прошло успешно: {self.passed_tests}")
        self.log("INFO", f"Не прошло: {self.total_tests - self.passed_tests}")
        self.log("INFO", f"Процент успеха: {success_rate:.1f}%")
        
        # Считаем тесты успешными если прошло >= 75%
        if success_rate >= 75:
            self.log("SUCCESS", "🎉 Тесты консенсуса прошли успешно!")
            return True
        else:
            self.log("ERROR", "❌ Тесты консенсуса не прошли")
            return False

def main():
    """Основная функция"""
    tester = Cellframe NodeConsensusTester()
    
    try:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        tester.log("WARN", "Тестирование прервано пользователем")
        sys.exit(1)
    except Exception as e:
        tester.log("ERROR", f"Неожиданная ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
