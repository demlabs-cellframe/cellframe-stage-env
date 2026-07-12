"""
Detect whether a chain stores atoms as DAG events or blockchain blocks.

Historically zerochain was always DAG-PoA, so many waiters hardcoded
``chain == "zerochain" → DAG``. ChipChain (and ESBOCS) zerochain uses blocks,
so consensus must be consulted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

DAG_CONSENSUS = frozenset({"dag_poa", "dag-poa", "dag", "dag_pos", "dag-pos"})
# Everything else (chipchain, esbocs, poa, …) is block-based.


def consensus_uses_dag(consensus: Optional[str]) -> bool:
    if not consensus:
        return False
    return consensus.strip().lower().replace("-", "_") in {
        "dag_poa",
        "dag",
        "dag_pos",
    }


def parse_consensus_from_chain_cfg(text: str) -> Optional[str]:
    """Extract ``consensus=`` from a chain .cfg body."""
    if not text:
        return None
    match = re.search(
        r"(?im)^\s*consensus\s*=\s*([^\s#;]+)",
        text,
    )
    return match.group(1).strip() if match else None


def read_chain_consensus_from_host(
    chain: str,
    network: str = "stagenet",
    node_id: int = 1,
) -> Optional[str]:
    """
    Read consensus type from host-side generated chain config.

    Returns None when the file is missing or unreadable.
    """
    try:
        from ..config.manager import get_config_loader

        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get("cache_dir", "cache")
        cache_dir = (config_loader.base_path / cache_dir_relative).resolve()
        cfg_path = (
            cache_dir
            / "configs"
            / f"node{node_id}"
            / "network"
            / network
            / f"{chain}.cfg"
        )
        if not cfg_path.exists():
            return None
        return parse_consensus_from_chain_cfg(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def chain_uses_dag(
    chain: str,
    consensus: Optional[str] = None,
    *,
    network: str = "stagenet",
    node_id: int = 1,
) -> bool:
    """
    Return True if the chain uses DAG events (not blocks).

    Resolution order:
    1. Explicit ``consensus`` argument
    2. Host chain config ``consensus=``
    3. Legacy name heuristic (zerochain → DAG) only when config is unavailable
    """
    if consensus is not None:
        return consensus_uses_dag(consensus)

    detected = read_chain_consensus_from_host(chain, network=network, node_id=node_id)
    if detected is not None:
        return consensus_uses_dag(detected)

    # Last-resort legacy: only zerochain-like names defaulted to DAG historically
    return chain.lower() in {"zerochain", "zero", "0"}
