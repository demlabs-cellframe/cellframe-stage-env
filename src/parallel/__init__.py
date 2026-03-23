"""
Parallel test execution support.

Provides shard-based isolation so that multiple test suites can run
concurrently without interfering with each other.  Each shard gets:

* Unique Docker Compose project name  (``cellframe-stage-0``, ``-1``, …)
* Unique Docker network subnet        (``172.22.0.0/24``, ``172.22.1.0/24``, …)
* Unique host port range               (``18000+``, ``18100+``, …)
* Dedicated cache directory             (``cache/shard-0/``, ``cache/shard-1/``, …)
* Dedicated compose file                (``docker-compose.shard-0.yml``, …)
"""

from .shard import ShardContext

__all__ = ["ShardContext"]
