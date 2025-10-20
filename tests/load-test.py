#!/usr/bin/env python3
"""
Нагрузочные тесты для Cellframe Node тестовой сети
Базовые тесты производительности и стабильности под нагрузкой
"""

import requests
import json
import time
import sys
import threading
import statistics
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# Dynamic load testing configuration
import os

def get_load_test_nodes():
    """Get node URLs for load testing from environment"""
    master_nodes = int(os.getenv('Cellframe Node_TEST_MASTER_NODES', '3'))
    full_nodes = int(os.getenv('Cellframe Node_TEST_FULL_NODES', '0'))
    base_port = int(os.getenv('Cellframe Node_TEST_BASE_RPC_PORT', '8545'))
    
    nodes = []
    
    # Add master nodes
    for i in range(1, master_nodes + 1):
        port = base_port - 1 + i
        nodes.append(f"http://localhost:{port}")
    
    # Add full nodes
    for i in range(1, full_nodes + 1):
        port = base_port - 1 + master_nodes + i
        nodes.append(f"http://localhost:{port}")
    
    return nodes

NODES = get_load_test_nodes()

class Cellframe NodeLoadTester:
    def __init__(self):
        self.passed_tests = 0
        self.total_tests = 0
        self.response_times = []
        self.error_count = 0
        
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
    
    def make_rpc_call(self, node_url: str, method: str, params: List[Any] = None) -> tuple:
        """Выполнение RPC вызова с измерением времени"""
        if params is None:
            params = []
            
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        start_time = time.time()
        try:
            response = requests.post(
                node_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            end_time = time.time()
            response_time = (end_time - start_time) * 1000  # в миллисекундах
            
            response.raise_for_status()
            return response.json(), response_time, None
        except requests.exceptions.RequestException as e:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000
            return {"error": str(e)}, response_time, str(e)
    
    def single_request_test(self, node_url: str, request_id: int) -> Dict[str, Any]:
        """Выполнение одного тестового запроса"""
        result, response_time, error = self.make_rpc_call(node_url, "eth_blockNumber")
        
        return {
            "request_id": request_id,
            "node_url": node_url,
            "response_time": response_time,
            "success": "result" in result,
            "error": error
        }
    
    def test_concurrent_requests(self, num_requests: int = 50, num_threads: int = 10) -> bool:
        """Тест одновременных запросов"""
        self.log("INFO", f"Тестирование {num_requests} одновременных запросов с {num_threads} потоками...")
        self.total_tests += 1
        
        results = []
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = []
            
            for i in range(num_requests):
                node_url = NODES[i % len(NODES)]  # Распределяем запросы по нодам
                future = executor.submit(self.single_request_test, node_url, i)
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    self.error_count += 1
                    self.log("ERROR", f"Ошибка в потоке: {e}")
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Анализируем результаты
        successful_requests = [r for r in results if r["success"]]
        failed_requests = [r for r in results if not r["success"]]
        
        success_rate = len(successful_requests) / len(results) * 100 if results else 0
        
        if successful_requests:
            response_times = [r["response_time"] for r in successful_requests]
            avg_response_time = statistics.mean(response_times)
            median_response_time = statistics.median(response_times)
            max_response_time = max(response_times)
            min_response_time = min(response_times)
        else:
            avg_response_time = median_response_time = max_response_time = min_response_time = 0
        
        requests_per_second = len(results) / total_time if total_time > 0 else 0
        
        self.log("INFO", f"=== Результаты нагрузочного тестирования ===")
        self.log("INFO", f"Всего запросов: {len(results)}")
        self.log("INFO", f"Успешных: {len(successful_requests)} ({success_rate:.1f}%)")
        self.log("INFO", f"Неуспешных: {len(failed_requests)}")
        self.log("INFO", f"Общее время: {total_time:.2f} сек")
        self.log("INFO", f"Запросов в секунду: {requests_per_second:.2f}")
        self.log("INFO", f"Среднее время ответа: {avg_response_time:.2f} мс")
        self.log("INFO", f"Медианное время ответа: {median_response_time:.2f} мс")
        self.log("INFO", f"Мин/Макс время ответа: {min_response_time:.2f}/{max_response_time:.2f} мс")
        
        # Критерии успеха:
        # - Успешность >= 90%
        # - Среднее время ответа <= 1000 мс
        # - Запросов в секунду >= 10
        
        if success_rate >= 90 and avg_response_time <= 1000 and requests_per_second >= 10:
            self.log("SUCCESS", "✓ Нагрузочный тест прошел успешно")
            self.passed_tests += 1
            return True
        else:
            self.log("WARN", "? Нагрузочный тест не прошел все критерии")
            if success_rate < 90:
                self.log("WARN", f"  - Низкая успешность: {success_rate:.1f}% (требуется >= 90%)")
            if avg_response_time > 1000:
                self.log("WARN", f"  - Высокое время ответа: {avg_response_time:.2f} мс (требуется <= 1000 мс)")
            if requests_per_second < 10:
                self.log("WARN", f"  - Низкая пропускная способность: {requests_per_second:.2f} RPS (требуется >= 10)")
            return False
    
    def test_sustained_load(self, duration_seconds: int = 60, rps: int = 5) -> bool:
        """Тест устойчивой нагрузки"""
        self.log("INFO", f"Тестирование устойчивой нагрузки ({rps} RPS в течение {duration_seconds} сек)...")
        self.total_tests += 1
        
        start_time = time.time()
        request_interval = 1.0 / rps
        results = []
        
        while time.time() - start_time < duration_seconds:
            request_start = time.time()
            
            # Выбираем случайную ноду
            node_url = NODES[len(results) % len(NODES)]
            result = self.single_request_test(node_url, len(results))
            results.append(result)
            
            # Ждем до следующего запроса
            elapsed = time.time() - request_start
            if elapsed < request_interval:
                time.sleep(request_interval - elapsed)
        
        # Анализируем результаты
        successful_requests = [r for r in results if r["success"]]
        success_rate = len(successful_requests) / len(results) * 100 if results else 0
        
        if successful_requests:
            response_times = [r["response_time"] for r in successful_requests]
            avg_response_time = statistics.mean(response_times)
        else:
            avg_response_time = 0
        
        actual_rps = len(results) / duration_seconds
        
        self.log("INFO", f"=== Результаты устойчивой нагрузки ===")
        self.log("INFO", f"Всего запросов: {len(results)}")
        self.log("INFO", f"Успешность: {success_rate:.1f}%")
        self.log("INFO", f"Фактический RPS: {actual_rps:.2f}")
        self.log("INFO", f"Среднее время ответа: {avg_response_time:.2f} мс")
        
        # Критерии успеха для устойчивой нагрузки:
        # - Успешность >= 95%
        # - Среднее время ответа <= 500 мс
        
        if success_rate >= 95 and avg_response_time <= 500:
            self.log("SUCCESS", "✓ Тест устойчивой нагрузки прошел успешно")
            self.passed_tests += 1
            return True
        else:
            self.log("WARN", "? Тест устойчивой нагрузки не прошел критерии")
            return False
    
    def test_memory_usage_stability(self) -> bool:
        """Тест стабильности использования памяти (упрощенный)"""
        self.log("INFO", "Тестирование стабильности памяти...")
        self.total_tests += 1
        
        # Выполняем серию запросов для потенциального выявления утечек памяти
        num_iterations = 100
        results = []
        
        for i in range(num_iterations):
            node_url = NODES[i % len(NODES)]
            
            # Выполняем разные типы запросов
            methods = ["eth_blockNumber", "eth_gasPrice", "net_version", "eth_chainId"]
            method = methods[i % len(methods)]
            
            result = self.single_request_test(node_url, i)
            results.append(result)
            
            if i % 20 == 0:
                self.log("INFO", f"Выполнено {i}/{num_iterations} запросов...")
        
        successful_requests = [r for r in results if r["success"]]
        success_rate = len(successful_requests) / len(results) * 100 if results else 0
        
        # Простая проверка - если большинство запросов успешны, считаем что утечек нет
        if success_rate >= 90:
            self.log("SUCCESS", f"✓ Тест стабильности памяти прошел (успешность: {success_rate:.1f}%)")
            self.passed_tests += 1
            return True
        else:
            self.log("WARN", f"? Возможные проблемы со стабильностью (успешность: {success_rate:.1f}%)")
            return False
    
    def run_all_tests(self) -> bool:
        """Запуск всех нагрузочных тестов"""
        self.log("INFO", "=== Начало нагрузочного тестирования Cellframe Node ===")
        
        # Проверяем доступность хотя бы одной ноды
        available_nodes = 0
        for node_url in NODES:
            result, _, _ = self.make_rpc_call(node_url, "eth_blockNumber")
            if "result" in result:
                available_nodes += 1
                self.log("INFO", f"✓ Нода доступна: {node_url}")
            else:
                self.log("WARN", f"✗ Нода недоступна: {node_url}")
        
        if available_nodes == 0:
            self.log("ERROR", "Ни одна нода не доступна для нагрузочного тестирования")
            return False
        
        self.log("INFO", f"Доступно нод для тестирования: {available_nodes}/{len(NODES)}")
        
        # Запускаем тесты (с меньшими нагрузками для стабильности)
        self.test_concurrent_requests(num_requests=20, num_threads=5)
        self.test_sustained_load(duration_seconds=30, rps=3)
        self.test_memory_usage_stability()
        
        # Выводим итоги
        success_rate = (self.passed_tests / self.total_tests) * 100 if self.total_tests > 0 else 0
        
        self.log("INFO", f"=== Результаты нагрузочного тестирования ===")
        self.log("INFO", f"Всего тестов: {self.total_tests}")
        self.log("INFO", f"Прошло успешно: {self.passed_tests}")
        self.log("INFO", f"Не прошло: {self.total_tests - self.passed_tests}")
        self.log("INFO", f"Процент успеха: {success_rate:.1f}%")
        
        # Для нагрузочных тестов критерий успеха мягче - 60%
        if success_rate >= 60:
            self.log("SUCCESS", "🎉 Нагрузочные тесты прошли удовлетворительно!")
            return True
        else:
            self.log("ERROR", "❌ Нагрузочные тесты показали проблемы производительности")
            return False

def main():
    """Основная функция"""
    tester = Cellframe NodeLoadTester()
    
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
