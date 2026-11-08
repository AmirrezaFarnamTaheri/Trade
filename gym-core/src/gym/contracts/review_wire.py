"""Exact native operator-review frames. A receipt is never a trading capability."""

import re

from ..domain.market_models import fields

REQUEST_SIZE, REPLY_SIZE, TICKET_SIZE = 400, 432, 352
U64 = (1 << 64) - 1
TICKET_FIELDS = "client_id account base quote side base_decimals price_decimals quote_decimals base_epoch quote_epoch runtime_epoch ceiling_sequence expires_at_ms quantity worst_price max_quote_debit min_quote_credit preview_hash rules_hash credential_generation"


def _small(value, maximum, *, positive=False):
    if type(value) is not int or not int(positive) <= value <= maximum:
        raise ValueError("invalid declared unit or precision")
    return value


def _uint(value, *, positive=False):
    if (
        type(value) is not str
        or not re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", value)
        or not int(positive) <= int(value) <= U64
    ):
        raise ValueError(
            "native identifiers and clocks require exact unsigned integer strings"
        )
    return int(value)


def _quanta(value, decimals):
    if (
        type(value) is not str
        or len(value) > 40
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)
    ):
        raise ValueError("amount requires exact nonnegative plain decimal text")
    whole, _, fraction = value.partition(".")
    if len(fraction) > decimals:
        raise ValueError("amount exceeds declared precision; rounding refused")
    result = int(whole + fraction + "0" * (decimals - len(fraction)))
    if result > U64:
        raise ValueError("native amount overflow")
    return result


def _digest(value, length):
    if (
        type(value) is not str
        or not re.fullmatch(rf"[0-9a-f]{{{length * 2}}}", value)
        or int(value, 16) == 0
    ):
        raise ValueError("invalid native evidence digest or generation")
    return bytes.fromhex(value)


def _name(value, maximum, *, asset=False):
    if (
        type(value) is not str
        or not 1 <= len(value) <= maximum
        or not re.fullmatch(r"[A-Z0-9]+" if asset else r"[A-Za-z0-9_.-]+", value)
    ):
        raise ValueError("invalid native ticket identity")
    return value.encode("ascii")


def ticket_bytes(value):
    fields(value, TICKET_FIELDS)
    if value["side"] not in ("BUY", "SELL") or value["base"] == value["quote"]:
        raise ValueError("invalid native side or asset pair")
    raw = bytearray(TICKET_SIZE)
    raw[0] = 1 if value["side"] == "BUY" else 2
    for i, key in enumerate(("base_decimals", "price_decimals", "quote_decimals"), 1):
        raw[i] = _small(value[key], 18)
    for i, (key, offset, size) in enumerate(
        (
            ("client_id", 152, 64),
            ("account", 216, 32),
            ("base", 248, 16),
            ("quote", 264, 16),
        )
    ):
        text = _name(value[key], size, asset=i >= 2)
        raw[4 + i] = len(text)
        raw[offset : offset + len(text)] = text
    for offset, key in ((8, "base_epoch"), (12, "quote_epoch")):
        raw[offset : offset + 4] = _small(
            value[key], (1 << 32) - 1, positive=True
        ).to_bytes(4, "big")
    amounts = [
        _quanta(value[key], value[scale])
        for key, scale in (
            ("quantity", "base_decimals"),
            ("worst_price", "price_decimals"),
            ("max_quote_debit", "quote_decimals"),
            ("min_quote_credit", "quote_decimals"),
        )
    ]
    if 0 in amounts[:2]:
        raise ValueError("native quantity and limit price must be positive")
    gross, scale = (
        amounts[0] * amounts[1],
        value["base_decimals"] + value["price_decimals"] - value["quote_decimals"],
    )
    gross = (
        ((gross + 10**scale - 1) // 10**scale if raw[0] == 1 else gross // 10**scale)
        if scale >= 0
        else gross * 10 ** (-scale)
    )
    if (
        gross > U64
        or (raw[0] == 1 and (amounts[2] < gross or amounts[3] != 0))
        or (raw[0] == 2 and (amounts[2] != 0 or not 0 < amounts[3] <= gross))
    ):
        raise ValueError("invalid native quote envelope")
    numbers = [
        _uint(value[key], positive=True)
        for key in ("runtime_epoch", "ceiling_sequence", "expires_at_ms")
    ] + amounts
    for i, number in enumerate(numbers):
        raw[16 + i * 8 : 24 + i * 8] = number.to_bytes(8, "big")
    raw[72:104], raw[104:136], raw[136:152] = (
        _digest(value["preview_hash"], 32),
        _digest(value["rules_hash"], 32),
        _digest(value["credential_generation"], 16),
    )
    return bytes(raw)


def _amount(value, decimals):
    return (
        str(value)
        if decimals == 0
        else f"{value // 10**decimals}.{value % 10**decimals:0{decimals}d}"
    )


def parse_ticket(raw):
    if (
        len(raw) != TICKET_SIZE
        or raw[0] not in (1, 2)
        or any(d > 18 for d in raw[1:4])
        or any(raw[4 + i] > size for i, size in enumerate((64, 32, 16, 16)))
    ):
        raise ValueError("invalid native ticket frame")
    try:
        value = {
            key: raw[offset : offset + raw[4 + i]].decode("ascii")
            for i, (key, offset) in enumerate(
                (("client_id", 152), ("account", 216), ("base", 248), ("quote", 264))
            )
        }
    except UnicodeError:
        raise ValueError("invalid native ticket text") from None
    value.update(
        side="BUY" if raw[0] == 1 else "SELL",
        base_decimals=raw[1],
        price_decimals=raw[2],
        quote_decimals=raw[3],
        base_epoch=int.from_bytes(raw[8:12], "big"),
        quote_epoch=int.from_bytes(raw[12:16], "big"),
    )
    for i, key in enumerate(("runtime_epoch", "ceiling_sequence", "expires_at_ms")):
        value[key] = str(int.from_bytes(raw[16 + i * 8 : 24 + i * 8], "big"))
    for i, (key, scale) in enumerate(
        (
            ("quantity", raw[1]),
            ("worst_price", raw[2]),
            ("max_quote_debit", raw[3]),
            ("min_quote_credit", raw[3]),
        )
    ):
        value[key] = _amount(int.from_bytes(raw[40 + i * 8 : 48 + i * 8], "big"), scale)
    value.update(
        preview_hash=raw[72:104].hex(),
        rules_hash=raw[104:136].hex(),
        credential_generation=raw[136:152].hex(),
    )
    if ticket_bytes(value) != raw:
        raise ValueError("noncanonical native ticket")
    return value


def encode_request(value, correlation):
    if (
        type(correlation) is not bytes
        or len(correlation) != 16
        or correlation == bytes(16)
    ):
        raise ValueError("invalid review correlation")
    raw = bytearray(REQUEST_SIZE)
    raw[:8], raw[16:32] = b"TGREVW01", correlation
    action = value.get("action") if type(value) is dict else None
    if action == "status":
        fields(value, "action")
        raw[8] = 1
    elif action in ("inspect", "revoke", "prepare"):
        fields(
            value,
            "action client_id" + (" expected_sequence" if action != "inspect" else ""),
        )
        identity = _name(value["client_id"], 64)
        raw[8], raw[9], raw[48 : 48 + len(identity)] = (
            {"inspect": 2, "revoke": 4, "prepare": 5}[action],
            len(identity),
            identity,
        )
        if action != "inspect":
            raw[32:40] = _uint(value["expected_sequence"], positive=True).to_bytes(
                8, "big"
            )
    elif action == "approve":
        fields(value, "action ticket")
        raw[8], raw[48:] = 3, ticket_bytes(value["ticket"])
    else:
        raise ValueError("unsupported native review action")
    return bytes(raw)


def decode_reply(raw, correlation, request):
    if (
        type(raw) is not bytes
        or len(raw) != REPLY_SIZE
        or raw[:8] != b"TGREPLY1"
        or raw[16:32] != correlation
        or raw[8] not in range(1, 8)
        or raw[9] > 3
        or raw[10] > 1
        or any(raw[11:16])
    ):
        raise ValueError("invalid native review reply")
    allowed = {
        "status": (1, 5, 6),
        "inspect": (2, 3, 4, 5, 6, 7),
        "approve": (2, 5, 6),
        "revoke": (3, 4, 5, 6),
        "prepare": (4, 5, 6, 7),
    }
    if raw[8] not in allowed.get(request.get("action"), ()):
        raise ValueError("native review state differs from requested action")
    sequence, at, epoch = (
        int.from_bytes(raw[offset : offset + 8], "big") for offset in (40, 48, 32)
    )
    has_ticket = raw[8] in (2, 3, 7)
    if (
        epoch == 0
        or bool(raw[10]) != has_ticket
        or has_ticket != (sequence > 0 and at > 0)
        or (not has_ticket and (sequence or at or any(raw[80:])))
    ):
        raise ValueError("invalid native review evidence")
    ticket = parse_ticket(raw[80:]) if has_ticket else None
    if ticket and (
        (
            request["action"] == "approve"
            and raw[8] == 2
            and ticket_bytes(ticket) != ticket_bytes(request["ticket"])
        )
        or (
            request["action"] in ("inspect", "revoke", "prepare")
            and ticket["client_id"] != request["client_id"]
        )
    ):
        raise ValueError("native receipt differs from requested ticket")
    if (
        request["action"] in ("revoke", "prepare")
        and raw[8] == {"revoke": 3, "prepare": 7}[request["action"]]
        and sequence <= _uint(request["expected_sequence"], positive=True)
    ):
        raise ValueError("native review version did not advance")
    return {
        "state": (
            "STATUS",
            "APPROVAL_RECORDED",
            "REVOKED",
            "MISSING",
            "DEFERRED",
            "REFUSED",
            "PREPARED",
        )[raw[8] - 1],
        "mode": ("DISARMED", "PAUSED", "EXIT_ONLY", "HALTED")[raw[9]],
        "current_epoch": str(epoch),
        "current_ceiling_sequence": str(int.from_bytes(raw[56:64], "big")),
        "current_credential_generation": raw[64:80].hex(),
        "sequence": str(sequence),
        "recorded_at_ms": str(at),
        "ticket": ticket,
        "funded_authority": False,
        "order_submitted": False,
        "automatic_retry_allowed": False,
        "limitation": "Native operator intent only. No verified holdings, fee contract, method certification or permission to send orders.",
    }
