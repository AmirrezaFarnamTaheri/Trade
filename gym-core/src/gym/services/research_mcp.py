"""Fixed R0 stdio MCP tools. No credentials, proposals, writes or dynamic tools."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from ..domain.registry import catalog
from .research import coverage
from .research_ledger import ResearchLedger

_TOOLS = [
    {"name": "strategy_catalog", "description": "List registered paper strategies.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "research_state", "description": "Read paper hypotheses, shadows, research jobs and alerts.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "market_coverage", "description": "Read observed public market coverage; gaps are not certification.",
     "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string", "pattern": "^[A-Z0-9]{2,24}$"}},
                     "required": ["symbol"], "additionalProperties": False}},
]


def handle(request, root):
    if type(request) is not dict or request.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    key = request.get("id")
    if "id" not in request:
        return None
    if (type(key) is not int and type(key) is not str) or (isinstance(key, str) and len(key) > 96):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request ID"}}
    response = {"jsonrpc": "2.0", "id": key}
    method, params = request.get("method"), request.get("params", {})
    if type(method) is not str or type(params) is not dict:
        return {**response, "error": {"code": -32602, "message": "Invalid params"}}
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "tradinggym-paper-research", "version": "1"}}
    elif method == "ping" and not params:
        result = {}
    elif method == "tools/list" and not params:
        result = {"tools": _TOOLS}
    elif method == "tools/call":
        try:
            if set(params) != {"name", "arguments"} or type(params["arguments"]) is not dict:
                raise ValueError("invalid tool call")
            name, args = params["name"], params["arguments"]
            root = Path(root)
            if name == "strategy_catalog" and not args:
                value = {"strategies": catalog(), "authority": "PAPER_ONLY", "funded_authority": False}
            elif name == "research_state" and not args:
                with ResearchLedger(root / "research.sqlite3", readonly=True) as ledger:
                    value = ledger.overview()
            elif name == "market_coverage" and set(args) == {"symbol"}:
                path = root / "market.db"
                if path.is_symlink():
                    raise ValueError("linked market database")
                with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
                    conn.execute("PRAGMA query_only=ON")
                    value = coverage(SimpleNamespace(c=conn), args["symbol"])
                value = {**value, "authority": "PUBLIC_OBSERVATIONS", "funded_authority": False}
            else:
                raise ValueError("unknown or non-read-only research tool")
            result = {"content": [{"type": "text", "text": json.dumps(value, allow_nan=False)}], "isError": False}
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
            result = {"content": [{"type": "text", "text": "Read-only research request rejected or data unavailable."}], "isError": True}
    else:
        return {**response, "error": {"code": -32601, "message": "Method not found"}}
    return {**response, "result": result}


def serve_stdio(root, source=None, sink=None):
    source, sink = source or sys.stdin, sink or sys.stdout
    while True:
        line = source.readline(65537)
        if not line:
            return 0
        if len(line) > 65536:
            sink.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Request exceeds 64 KiB"}}) + "\n")
            sink.flush()
            return 2
        try:
            request = json.loads(line)
            response = handle(request, root)
        except (ValueError, RecursionError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            sink.write(json.dumps(response, allow_nan=False) + "\n")
            sink.flush()
