"""Push the workspace health to the operator when it changes, so a stalled collector or stale backup is noticed.

Channels: a Windows toast (no setup) and, optionally, one HTTPS webhook that accepts a plain-text POST, for
example an ntfy.sh topic that pushes to a phone. Only a change in the set of failing or warning checks is sent,
plus one message when everything recovers, so a scheduled run every half hour never repeats itself.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

STATE_FILE = "alert_state.json"
_TOAST = r"""
$title = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{title}'))
$body = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{body}'))
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $xml.GetElementsByTagName('text')
[void]$text.Item(0).AppendChild($xml.CreateTextNode($title))
[void]$text.Item(1).AppendChild($xml.CreateTextNode($body))
$app = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def _signature(report: dict) -> list[list[str]]:
    return sorted([c["check"], c["status"]] for c in report["checks"] if c["status"] in ("WARN", "FAIL"))


def message(report: dict, previous: list | None) -> tuple[str, str] | None:
    """(title, body) when the alerting set changed since `previous`, else None."""
    current = _signature(report)
    if current == (previous or []):
        return None
    if not current:
        return "TradingGYM recovered", "All health checks pass again."
    lines = [f"{c['status']} {c['check']}: {c['detail']}" for c in report["checks"] if c["status"] in ("WARN", "FAIL")]
    return f"TradingGYM {report['status']}", "\n".join(lines[:6])[:900]


def toast(title: str, body: str) -> bool:
    if os.name != "nt":
        return False
    encode = lambda text: base64.b64encode(text.encode("utf-8")).decode("ascii")
    script = _TOAST.format(title=encode(title), body=encode(body))
    command = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
                            capture_output=True, timeout=30, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.returncode == 0


def webhook(url: str, title: str, body: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("alert webhook must be an https URL without credentials")
    request = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                     headers={"Title": title, "Content-Type": "text/plain; charset=utf-8"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return 200 <= response.status < 300


def notify(report: dict, root: Path, *, webhook_url: str | None = None, use_toast: bool = True) -> dict:
    """Send once per change; the state file remembers what was last sent."""
    path = root / STATE_FILE
    try:
        previous = json.loads(path.read_text("utf-8")).get("alerting") if path.is_file() else None
    except (OSError, ValueError):
        previous = None
    composed = message(report, previous)
    if composed is None:
        return {"sent": False, "reason": "unchanged"}
    title, body = composed
    channels = {}
    if use_toast:
        channels["toast"] = toast(title, body)
    if webhook_url:
        try:
            channels["webhook"] = webhook(webhook_url, title, body)
        except (OSError, ValueError) as error:
            channels["webhook"] = f"failed: {type(error).__name__}"
    # Remember the state only once a channel delivered, so a failed send is retried next run.
    if any(v is True for v in channels.values()) or not channels:
        path.write_text(json.dumps({"alerting": _signature(report), "at": report["as_of"]}), "utf-8")
    return {"sent": True, "title": title, "channels": channels}
