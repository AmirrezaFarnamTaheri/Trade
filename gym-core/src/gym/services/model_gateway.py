"""Optional trusted-host provider bridge, never imported by the R0 research worker."""
from __future__ import annotations

import os
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

# ponytail: source-checkout bridge; package JS resources when distributing wheels.
_ENTRY = Path(__file__).resolve().parents[4] / "model-gateway" / "gateway.mjs"


class ModelGateway:
    """One private, bounded stdio channel; no arbitrary command execution or TCP listener."""

    def __init__(self):
        self._process = None
        self._lock = asyncio.Lock()
        self._sequence = 0

    async def close(self):
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    async def request(self, action, value=None):
        payload = json.dumps({"id": 0, "action": action, "value": value}).encode()
        if len(payload) > 1024 * 1024:
            raise ValueError("model request too large")
        if self._lock.locked():
            raise ValueError("model gateway busy")
        async with self._lock:
            try:
                async with asyncio.timeout(140):
                    if self._process is None or self._process.returncode is not None:
                        node = shutil.which("node")
                        if node is None or not _ENTRY.with_name("host.mjs").is_file():
                            raise ValueError("model gateway unavailable")
                        self._process = await asyncio.create_subprocess_exec(
                            node, str(_ENTRY.with_name("host.mjs")),
                            env=dict(os.environ, GYM_MODEL_PYTHON=sys.executable),
                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL, limit=4 * 1024 * 1024,
                            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                    self._sequence += 1
                    payload = json.dumps({"id": self._sequence, "action": action, "value": value}).encode()
                    self._process.stdin.write(payload + b"\n")
                    await self._process.stdin.drain()
                    try:
                        reply = json.loads(await self._process.stdout.readline())
                    except ValueError:
                        await self.close()
                        raise ValueError("model gateway unavailable") from None
                    if not isinstance(reply, dict) or reply.get("id") != self._sequence:
                        await self.close()
                        raise ValueError("invalid model gateway reply")
                    if "error" in reply:
                        # Only gateway-owned error codes cross this boundary, never provider diagnostics.
                        raise ValueError("model gateway: " + reply["error"])
                    return reply["result"]
            except ValueError:
                raise
            except asyncio.CancelledError:
                await self.close()
                raise
            except (OSError, TimeoutError, KeyError, TypeError):
                await self.close()
                raise ValueError("model gateway unavailable or request interrupted") from None


def run(argv: list[str]) -> int:
    node = shutil.which("node")
    if not node:
        print("error: model gateway requires Node.js >=22.19.0", file=sys.stderr)
        return 2
    if not _ENTRY.is_file():
        print("error: model gateway requires the complete source checkout", file=sys.stderr)
        return 2
    env = dict(os.environ, GYM_MODEL_PYTHON=sys.executable)
    try:
        return subprocess.run([node, str(_ENTRY), *argv], env=env, check=False).returncode
    except OSError:
        print("error: could not start the optional model gateway", file=sys.stderr)
        return 2
