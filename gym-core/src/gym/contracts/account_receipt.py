"""Display-only service receipt validation; never an execution authority token."""
import re

_FIELDS = frozenset(("source", "authority", "resource", "sequence", "runtime_epoch",
                     "started_at_ms", "received_at_ms", "credential_generation",
                     "request_id", "response_digest", "event_hash"))


def service_receipts(value):
    if not isinstance(value, list) or len(value) > 104:
        raise ValueError("invalid service receipt collection")
    result, seen, requests = [], set(), set()
    for receipt in value:
        if not isinstance(receipt, dict):
            raise ValueError("invalid service receipt identity")
        order = receipt.get("resource") == "ORDER_STATUS"
        page = receipt.get("resource") in ("OPEN_ORDERS", "ORDER_HISTORY")
        identity = (receipt.get("resource"), receipt.get("client_id", ""), receipt.get("page", ""), receipt.get("per_page", ""))
        if receipt.keys() != (_FIELDS | {"client_id"} if order else _FIELDS | {"page", "per_page"} if page else _FIELDS) or (
            receipt.get("source") != "EXECUTOR_SERVICE_JOURNAL"
            or receipt.get("authority") != "OBSERVATION_ONLY"
            or receipt.get("resource") not in ("BALANCES", "FEES", "ORDER_STATUS", "OPEN_ORDERS", "ORDER_HISTORY")
            or (order and (not isinstance(receipt.get("client_id"), str)
                          or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", receipt["client_id"])))
        ):
            raise ValueError("invalid service receipt identity")
        if page and any(not isinstance(receipt[key], str) or not re.fullmatch(r"[1-9][0-9]{0,3}", receipt[key])
                        or int(receipt[key]) > maximum for key, maximum in (("page", 1000), ("per_page", 100))):
            raise ValueError("invalid service receipt page")
        if identity in seen:
            raise ValueError("repeated service receipt identity")
        for key in ("sequence", "runtime_epoch", "started_at_ms", "received_at_ms"):
            number = receipt[key]
            if not isinstance(number, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", number) or int(number) > 2**64 - 1:
                raise ValueError("invalid service receipt number")
        for key, size in (("credential_generation", 32), ("request_id", 32),
                          ("response_digest", 64), ("event_hash", 64)):
            if not isinstance(receipt[key], str) or not re.fullmatch(rf"[0-9a-f]{{{size}}}", receipt[key]) or int(receipt[key], 16) == 0:
                raise ValueError("invalid service receipt digest")
        if receipt["request_id"] in requests:
            raise ValueError("repeated service receipt request")
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
        seen.add(identity)
        requests.add(receipt["request_id"])
        result.append(dict(receipt))
    return result
