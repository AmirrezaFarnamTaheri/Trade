"""Display-only service receipt validation; never an execution authority token."""
import re

_FIELDS = frozenset(("source", "authority", "resource", "sequence", "runtime_epoch",
                     "started_at_ms", "received_at_ms", "credential_generation",
                     "request_id", "response_digest", "event_hash"))


def service_receipts(value):
    if not isinstance(value, list) or len(value) > 2:
        raise ValueError("invalid service receipt collection")
    result, seen = [], set()
    for receipt in value:
        if not isinstance(receipt, dict) or receipt.keys() != _FIELDS or (
            receipt.get("source") != "EXECUTOR_SERVICE_JOURNAL"
            or receipt.get("authority") != "OBSERVATION_ONLY"
            or receipt.get("resource") not in ("BALANCES", "FEES")
            or receipt["resource"] in seen
        ):
            raise ValueError("invalid service receipt identity")
        for key in ("sequence", "runtime_epoch", "started_at_ms", "received_at_ms"):
            number = receipt[key]
            if not isinstance(number, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", number) or int(number) > 2**64 - 1:
                raise ValueError("invalid service receipt number")
        for key, size in (("credential_generation", 32), ("request_id", 32),
                          ("response_digest", 64), ("event_hash", 64)):
            if not isinstance(receipt[key], str) or not re.fullmatch(rf"[0-9a-f]{{{size}}}", receipt[key]) or int(receipt[key], 16) == 0:
                raise ValueError("invalid service receipt digest")
        if not 0 <= int(receipt["received_at_ms"]) - int(receipt["started_at_ms"]) < 12_000:
            raise ValueError("invalid service receipt duration")
        if result:
            previous = result[-1]
            if any(receipt[key] != previous[key] for key in ("credential_generation", "runtime_epoch")) or (
                int(receipt["sequence"]) <= int(previous["sequence"])
                or int(receipt["started_at_ms"]) < int(previous["received_at_ms"])
                or receipt["request_id"] == previous["request_id"]
            ):
                raise ValueError("inconsistent service receipt context")
        seen.add(receipt["resource"])
        result.append(dict(receipt))
    return result
