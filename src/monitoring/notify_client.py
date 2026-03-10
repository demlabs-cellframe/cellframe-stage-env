"""
Async TCP client for the Cellframe Node notify server.

Connects directly to a container's notify server (0.0.0.0:8080) and streams
null-terminated JSON messages.  Each message is a JSON object with a "class"
field used for filtering.

Usage:
    client = NotifyClient()
    await client.connect("172.20.0.5", port=8080)
    async for msg in client.messages():
        if msg.get("class") == "VpnClientState":
            ...
    await client.close()
"""

import asyncio
import json
from typing import AsyncGenerator, Dict, Any, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)

NOTIFY_PORT_DEFAULT = 8080


class NotifyClient:
    """Async TCP client for the node notify server."""

    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._buffer = b""

    async def connect(self, host: str, port: int = NOTIFY_PORT_DEFAULT,
                      timeout: float = 5.0) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        logger.debug("notify_client_connected", host=host, port=port)

    async def messages(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Yield parsed JSON messages from the notify stream.

        Messages are framed by null bytes (\\x00) *or* \\r\\n (used for the
        initial burst sent to new clients).  Invalid JSON is silently skipped.
        """
        assert self._reader is not None, "call connect() first"
        while True:
            try:
                chunk = await self._reader.read(8192)
            except (ConnectionResetError, asyncio.IncompleteReadError):
                break
            if not chunk:
                break
            self._buffer += chunk

            while b'\0' in self._buffer or b'\r\n' in self._buffer:
                null_pos = self._buffer.find(b'\0')
                crlf_pos = self._buffer.find(b'\r\n')

                if null_pos == -1:
                    split_pos, skip = crlf_pos, 2
                elif crlf_pos == -1:
                    split_pos, skip = null_pos, 1
                else:
                    split_pos, skip = (null_pos, 1) if null_pos < crlf_pos else (crlf_pos, 2)

                raw = self._buffer[:split_pos]
                self._buffer = self._buffer[split_pos + skip:]

                if not raw.strip():
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("notify_bad_json", raw=raw[:200])

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None


async def wait_for_notify(
    host: str,
    port: int = NOTIFY_PORT_DEFAULT,
    notify_class: Optional[str] = None,
    contains: Optional[str] = None,
    not_contains: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """Connect to the notify server and wait for a matching message.

    Args:
        host: Container IP address.
        port: Notify server port (default 8080).
        notify_class: If set, only consider messages with this ``class`` value.
        contains: Substring that must appear in the JSON text.
        not_contains: Substring that must NOT appear in the JSON text.
        timeout: Total timeout in seconds.

    Returns:
        The first matching JSON message.

    Raises:
        asyncio.TimeoutError: if no matching message arrives within *timeout*.
    """
    client = NotifyClient()
    try:
        await client.connect(host, port, timeout=min(timeout, 10.0))

        async def _scan():
            async for msg in client.messages():
                if notify_class and msg.get("class") != notify_class:
                    continue
                text = json.dumps(msg)
                if contains and contains.lower() not in text.lower():
                    continue
                if not_contains and not_contains.lower() in text.lower():
                    continue
                return msg
            raise ConnectionError("notify stream closed before match")

        return await asyncio.wait_for(_scan(), timeout=timeout)
    finally:
        await client.close()
