"""TradingGYM T0 stop-only control-wire v1 reference codec.

No order, credential, arm or budget messages exist on this protocol. OS-level
pipe ACLs authenticate the caller; this frame does not authenticate anyone.
"""
from enum import IntEnum
from struct import Struct

MAGIC = b"TGSTOP01"
VERSION = 1
_FRAME = Struct(">8sHHBBBBQ16s")
FRAME_SIZE = _FRAME.size


class StopCommand(IntEnum):
    STATUS = 1
    PAUSE_ENTRIES = 2
    EXIT_ONLY = 3
    HALT = 4


class StopMode(IntEnum):
    DISARMED = 0
    PAUSED = 1
    EXIT_ONLY = 2
    HALTED = 3


class StopResult(IntEnum):
    ACK = 128
    STALE_RUNTIME = 129


def _validate_identity(epoch: int, correlation: bytes) -> None:
    if not isinstance(epoch, int) or isinstance(epoch, bool) or not 0 < epoch < 1 << 64:
        raise ValueError("invalid runtime epoch")
    if not isinstance(correlation, bytes) or len(correlation) != 16 or not any(correlation):
        raise ValueError("invalid correlation ID")


def _parse(raw: bytes):
    if not isinstance(raw, bytes) or len(raw) != FRAME_SIZE:
        raise ValueError("invalid stop-frame length")
    magic, version, length, code, mode, changed, reserved, epoch, correlation = _FRAME.unpack(raw)
    if magic != MAGIC or version != VERSION or length != FRAME_SIZE or reserved != 0:
        raise ValueError("unsupported or malformed stop-frame header")
    _validate_identity(epoch, correlation)
    return code, mode, changed, epoch, correlation


def encode_request(command: StopCommand, epoch: int, correlation: bytes) -> bytes:
    if not isinstance(command, StopCommand):
        raise ValueError("unknown T0 command")
    _validate_identity(epoch, correlation)
    return _FRAME.pack(MAGIC, VERSION, FRAME_SIZE, command.value, 0, 0, 0, epoch, correlation)


def decode_request(raw: bytes) -> tuple[StopCommand, int, bytes]:
    code, mode, changed, epoch, correlation = _parse(raw)
    if mode != 0 or changed != 0:
        raise ValueError("request contains response fields")
    try:
        command = StopCommand(code)
    except ValueError as err:
        raise ValueError("unsupported T0 command") from err
    return command, epoch, correlation


def encode_reply(result: StopResult, mode: StopMode, changed: bool, epoch: int, correlation: bytes) -> bytes:
    if not isinstance(result, StopResult) or not isinstance(mode, StopMode) or not isinstance(changed, bool):
        raise ValueError("invalid stop reply")
    _validate_identity(epoch, correlation)
    if result == StopResult.STALE_RUNTIME and changed:
        raise ValueError("stale runtime reply cannot change mode")
    return _FRAME.pack(MAGIC, VERSION, FRAME_SIZE, result.value, mode.value, int(changed), 0, epoch, correlation)


def decode_reply(raw: bytes) -> tuple[StopResult, StopMode, bool, int, bytes]:
    code, mode, changed, epoch, correlation = _parse(raw)
    try:
        result = StopResult(code)
        mode = StopMode(mode)
    except ValueError as err:
        raise ValueError("invalid stop reply enum") from err
    if changed not in (0, 1) or (result == StopResult.STALE_RUNTIME and changed):
        raise ValueError("invalid stop reply flag")
    return result, mode, bool(changed), epoch, correlation


def verify_reply_for(request: bytes, reply: bytes) -> tuple[StopMode, bool]:
    """Only a correlated ACK at the requested stop level confirms success.

    Pipe peer authorization belongs to the OS; absent acknowledgment is never
    success, and callers must display REQUESTED until verification completes.
    """
    command, epoch, correlation = decode_request(request)
    result, mode, changed, reply_epoch, reply_id = decode_reply(reply)
    if reply_id != correlation or result != StopResult.ACK or reply_epoch != epoch:
        raise ValueError("stop has not been acknowledged for this request")
    required = {
        StopCommand.STATUS: StopMode.DISARMED,
        StopCommand.PAUSE_ENTRIES: StopMode.PAUSED,
        StopCommand.EXIT_ONLY: StopMode.EXIT_ONLY,
        StopCommand.HALT: StopMode.HALTED,
    }[command]
    if mode < required:
        raise ValueError("acknowledgment does not confirm the requested stop level")
    return mode, changed
