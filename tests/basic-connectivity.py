#!/usr/bin/env python3
"""
Basic connectivity tests for Cellframe Node test network
Tests RPC endpoint availability and basic functionality with CF20 tokens
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

class Cellframe NodeConnectivityTester:
    def __init__(self):
        self.passed_tests = 0
        self.total_tests = 0
        
    def log(self, level: str, message: str):
        """Logging with timestamps"""
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
        """Execute RPC call to node"""
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
            self.log("ERROR", f"RPC вызов не удался: {e}")
            return {"error": str(e)}
    
    def test_node_connectivity(self, node: Dict[str, str]) -> bool:
        """Тест базовой связности с нодой"""
        self.log("INFO", f"Тестирование связности с {node['name']} ({node['url']})")
        self.total_tests += 1
        
        try:
            # Простой HTTP запрос
            response = requests.get(f"{node['url']}/health", timeout=5)
            if response.status_code == 200:
                self.log("SUCCESS", f"✓ {node['name']}: HTTP связность OK")
                self.passed_tests += 1
                return True
            else:
                self.log("ERROR", f"✗ {node['name']}: HTTP ошибка {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            self.log("ERROR", f"✗ {node['name']}: Связность не удалась - {e}")
            return False
    
    def test_rpc_methods(self, node: Dict[str, str]) -> bool:
        """Test basic RPC methods"""
        self.log("INFO", f"Testing RPC methods for {node['name']}")
        
        # List of basic methods for testing (CF20 compatible)
        methods = [
            ("eth_blockNumber", []),
            ("net_version", []),
            ("eth_chainId", []),
            ("cf20_getBalance", ["0x0000000000000000000000000000000000000000"]),  # CF20 balance check
            ("node_getInfo", []),  # Cellframe Node node information
        ]
        
        passed_methods = 0
        
        for method, params in methods:
            self.total_tests += 1
            result = self.make_rpc_call(node['url'], method, params)
            
            if "error" not in result and "result" in result:
                self.log("SUCCESS", f"✓ {node['name']}: {method} OK")
                self.passed_tests += 1
                passed_methods += 1
            else:
                error_msg = result.get("error", {}).get("message", "Неизвестная ошибка")
                self.log("ERROR", f"✗ {node['name']}: {method} FAIL - {error_msg}")
        
        return passed_methods == len(methods)
    
    def test_chain_info(self, node: Dict[str, str]) -> Dict[str, Any]:
        """Получение информации о чейне"""
        self.log("INFO", f"Получение информации о чейне от {node['name']}")
        
        chain_info = {}
        
        # Получаем номер блока
        result = self.make_rpc_call(node['url'], "eth_blockNumber")
        if "result" in result:
            block_number = int(result["result"], 16)
            chain_info["block_number"] = block_number
            self.log("INFO", f"{node['name']}: Текущий блок #{block_number}")
        
        # Получаем chain ID
        result = self.make_rpc_call(node['url'], "eth_chainId")
        if "result" in result:
            chain_id = int(result["result"], 16)
            chain_info["chain_id"] = chain_id
            self.log("INFO", f"{node['name']}: Chain ID {chain_id}")
        
        # Получаем версию сети
        result = self.make_rpc_call(node['url'], "net_version")
        if "result" in result:
            network_version = result["result"]
            chain_info["network_version"] = network_version
            self.log("INFO", f"{node['name']}: Network Version {network_version}")
        
        return chain_info
    
    def test_consensus_sync(self) -> bool:
        """Тест синхронизации между нодами"""
        self.log("INFO", "Тестирование синхронизации консенсуса между нодами")
        self.total_tests += 1
        
        # Получаем информацию о блоках от всех нод
        node_blocks = []
        for node in NODES:
            result = self.make_rpc_call(node['url'], "eth_blockNumber")
            if "result" in result:
                block_number = int(result["result"], 16)
                node_blocks.append((node['name'], block_number))
                self.log("INFO", f"{node['name']}: Блок #{block_number}")
            else:
                self.log("WARN", f"{node['name']}: Не удалось получить номер блока")
        
        if len(node_blocks) < 2:
            self.log("ERROR", "✗ Недостаточно нод для проверки синхронизации")
            return False
        
        # Проверяем что разница в блоках не более 2 (допустимая разница)
        block_numbers = [block for _, block in node_blocks]
        min_block = min(block_numbers)
        max_block = max(block_numbers)
        
        if max_block - min_block <= 2:
            self.log("SUCCESS", f"✓ Ноды синхронизированы (разница: {max_block - min_block} блоков)")
            self.passed_tests += 1
            return True
        else:
            self.log("ERROR", f"✗ Ноды не синхронизированы (разница: {max_block - min_block} блоков)")
            return False
    
    def test_transaction_submission(self, node: Dict[str, str]) -> bool:
        """Тест отправки тестовой транзакции"""
        self.log("INFO", f"Тестирование отправки транзакции через {node['name']}")
        self.total_tests += 1
        
        # Простая тестовая транзакция (без подписи, только для проверки валидации)
        tx = {
            "from": "0x0000000000000000000000000000000000000000",
            "to": "0x0000000000000000000000000000000000000001",
            "value": "0x1",
            "gas": "0x5208",  # 21000 газа
            "gasPrice": "0x4a817c800",  # 20 Gwei
        }
        
        # Пытаемся отправить транзакцию
        result = self.make_rpc_call(node['url'], "eth_sendTransaction", [tx])
        
        # Ожидаем ошибку (так как транзакция не подписана), но RPC должен отвечать
        if "error" in result:
            error_msg = result["error"].get("message", "")
            if "signature" in error_msg.lower() or "unauthorized" in error_msg.lower():
                self.log("SUCCESS", f"✓ {node['name']}: RPC валидация транзакций работает")
                self.passed_tests += 1
                return True
            else:
                self.log("WARN", f"? {node['name']}: Неожиданная ошибка - {error_msg}")
                return False
        else:
            self.log("WARN", f"? {node['name']}: Транзакция принята (неожиданно)")
            return True
    
    def run_all_tests(self) -> bool:
        """Запуск всех тестов связности"""
        self.log("INFO", "=== Начало тестирования базовой связности Cellframe Node ===")
        
        available_nodes = []
        
        # Тестируем связность с каждой нодой
        for node in NODES:
            if self.test_node_connectivity(node):
                available_nodes.append(node)
        
        if not available_nodes:
            self.log("ERROR", "Ни одна нода не доступна!")
            return False
        
        self.log("INFO", f"Доступно нод: {len(available_nodes)}/{len(NODES)}")
        
        # Тестируем RPC методы для доступных нод
        for node in available_nodes:
            self.test_rpc_methods(node)
            self.test_chain_info(node)
            self.test_transaction_submission(node)
        
        # Тестируем синхронизацию между нодами
        if len(available_nodes) > 1:
            self.test_consensus_sync()
        
        # Выводим итоги
        success_rate = (self.passed_tests / self.total_tests) * 100 if self.total_tests > 0 else 0
        
        self.log("INFO", f"=== Результаты тестирования ===")
        self.log("INFO", f"Всего тестов: {self.total_tests}")
        self.log("INFO", f"Прошло успешно: {self.passed_tests}")
        self.log("INFO", f"Не прошло: {self.total_tests - self.passed_tests}")
        self.log("INFO", f"Процент успеха: {success_rate:.1f}%")
        
        # Считаем тесты успешными если прошло >= 80%
        if success_rate >= 80:
            self.log("SUCCESS", "🎉 Тесты базовой связности прошли успешно!")
            return True
        else:
            self.log("ERROR", "❌ Тесты базовой связности не прошли")
            return False

def main():
    """Основная функция"""
    tester = Cellframe NodeConnectivityTester()
    
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
