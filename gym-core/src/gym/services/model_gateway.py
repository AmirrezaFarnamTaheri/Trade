"""Optional trusted-host provider bridge, never imported by the R0 research worker."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ponytail: source-checkout bridge; package JS resources when distributing wheels.
_ENTRY = Path(__file__).resolve().parents[4] / "model-gateway" / "gateway.mjs"

# The gateway holds provider credentials and links a large SDK tree, so it sees only what it needs:
# OS essentials, proxy and CA settings, its own GYM_MODEL_* switches, and the key variables its config names.
_BASE_ENV = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
    "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "XDG_STATE_HOME",
    "USERNAME", "USER", "LANG", "LC_ALL", "TZ", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "GYM_GATEWAY_PASSPHRASE", "GYM_GATEWAY_PLAINTEXT",
})


def _gateway_home(environ) -> Path:
    """Mirror of defaultHome() in model-gateway/state.mjs."""
    if environ.get("GYM_MODEL_HOME"):
        return Path(environ["GYM_MODEL_HOME"])
    if os.name == "nt":
        return Path(environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "TradingGYM/models"
    return Path(environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "tradinggym/models"


def _configured_key_names(environ) -> set[str]:
    try:
        config = json.loads((_gateway_home(environ) / "config.json").read_text(encoding="utf-8"))
        return {name for c in config.get("connections", [])
                if isinstance(c, dict) and isinstance(c.get("auth"), dict) and c["auth"].get("type") == "api_key"
                for name in c["auth"].get("env", []) if isinstance(name, str)}
    except (OSError, ValueError, AttributeError, TypeError):
        return set()  # no or unreadable config: the gateway itself reports it


def gateway_env(environ=None) -> dict[str, str]:
    """Allowlisted child environment, re-read at every spawn so newly configured key names apply on restart."""
    environ = os.environ if environ is None else environ
    keep = _BASE_ENV | _configured_key_names(environ)
    env = {k: v for k, v in environ.items()
           if k.upper() in keep or k.upper().startswith("GYM_MODEL_") or k in keep}
    env["GYM_MODEL_PYTHON"] = sys.executable
    return env



class GatewayUnavailable(ConnectionError):
    """The local Node gateway is missing, busy or stopped; the API answers 503, not a client error."""

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
            raise GatewayUnavailable("model gateway busy")
        async with self._lock:
            try:
                async with asyncio.timeout(140):
                    if self._process is None or self._process.returncode is not None:
                        node = shutil.which("node")
                        if node is None or not _ENTRY.with_name("host.mjs").is_file():
                            raise GatewayUnavailable("model gateway unavailable")
                        self._process = await asyncio.create_subprocess_exec(
                            node, str(_ENTRY.with_name("host.mjs")),
                            env=gateway_env(),
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
                        raise GatewayUnavailable("model gateway unavailable") from None
                    if not isinstance(reply, dict) or reply.get("id") != self._sequence:
                        await self.close()
                        raise ValueError("invalid model gateway reply")
                    if "error" in reply:
                        # Only gateway-owned error codes cross this boundary, never provider diagnostics.
                        raise ValueError("model gateway: " + reply["error"])
                    return reply["result"]
            except (ValueError, GatewayUnavailable):
                raise
            except asyncio.CancelledError:
                await self.close()
                raise
            except (OSError, TimeoutError, KeyError, TypeError):
                await self.close()
                raise GatewayUnavailable("model gateway unavailable or request interrupted") from None


def run(argv: list[str]) -> int:
    node = shutil.which("node")
    if not node:
        print("error: model gateway requires Node.js >=22.19.0", file=sys.stderr)
        return 2
    if not _ENTRY.is_file():
        print("error: model gateway requires the complete source checkout", file=sys.stderr)
        return 2
    env = gateway_env()
    try:
        return subprocess.run([node, str(_ENTRY), *argv], env=env, check=False).returncode
    except OSError:
        print("error: could not start the optional model gateway", file=sys.stderr)
        return 2
