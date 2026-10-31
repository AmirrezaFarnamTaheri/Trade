"""Byte-level fixtures for IPC-only T0 stop commands (no order authority)."""
import json
from pathlib import Path

import pytest

from gym.contracts.stop_wire import (
    StopCommand,
    StopMode,
    StopResult,
    decode_reply,
    decode_request,
    encode_reply,
    encode_request,
)

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/v1/fixtures/stop-wire-v1.json").read_text("utf-8")
)
CORRELATION = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
EPOCH = 0x0102030405060708


def test_fixed_size_stop_request_matches_golden_vector():
    raw = encode_request(StopCommand.PAUSE_ENTRIES, EPOCH, CORRELATION)
    assert len(raw) == 40
    assert raw.hex() == VECTORS["pause_request_hex"]
    assert decode_request(raw) == (StopCommand.PAUSE_ENTRIES, EPOCH, CORRELATION)


def test_ack_reply_echoes_correlation_and_requested_epoch():
    raw = encode_reply(StopResult.ACK, StopMode.PAUSED, True, EPOCH, CORRELATION)
    assert len(raw) == 40
    assert raw.hex() == VECTORS["paused_ack_hex"]
    assert decode_reply(raw) == (StopResult.ACK, StopMode.PAUSED, True, EPOCH, CORRELATION)


@pytest.mark.parametrize("byte_offset", [0, 8, 10, 13, 14, 15])
def test_mutated_request_header_rejected(byte_offset):
    raw = bytearray.fromhex(VECTORS["pause_request_hex"])
    raw[byte_offset] ^= 1
    with pytest.raises(ValueError):
        decode_request(bytes(raw))


@pytest.mark.parametrize("payload", [b"", b"G", b"\x00" * 39, b"\x00" * 41])
def test_truncated_or_oversized_request_rejected(payload):
    with pytest.raises(ValueError):
        decode_request(payload)


def test_unsupported_command_cannot_be_interpreted_as_t0_stop():
    raw = bytearray.fromhex(VECTORS["pause_request_hex"])
    raw[12] = 9
    with pytest.raises(ValueError):
        decode_request(bytes(raw))


def test_zero_epoch_or_correlation_is_rejected():
    for kwargs in ({"epoch": 0}, {"correlation": bytes(16)}):
        with pytest.raises(ValueError):
            encode_request(StopCommand.HALT, kwargs.get("epoch", EPOCH), kwargs.get("correlation", CORRELATION))


def test_status_read_is_only_non_mutating_stop_command():
    raw = encode_request(StopCommand.STATUS, EPOCH, CORRELATION)
    assert decode_request(raw)[0] == StopCommand.STATUS


def test_bad_reply_fields_or_request_bytes_are_not_acks():
    raw = bytearray.fromhex(VECTORS["paused_ack_hex"])
    raw[12] = 2
    with pytest.raises(ValueError):
        decode_reply(bytes(raw))
    raw = bytearray.fromhex(VECTORS["paused_ack_hex"])
    raw[13] = 7
    with pytest.raises(ValueError):
        decode_reply(bytes(raw))
    with pytest.raises(ValueError):
        decode_reply(bytes.fromhex(VECTORS["pause_request_hex"]))


def test_client_accepts_only_the_matching_acknowledged_stop():
    from gym.contracts.stop_wire import verify_reply_for

    request = encode_request(StopCommand.PAUSE_ENTRIES, EPOCH, CORRELATION)
    good = encode_reply(StopResult.ACK, StopMode.PAUSED, True, EPOCH, CORRELATION)
    assert verify_reply_for(request, good) == (StopMode.PAUSED, True)

    other_id = encode_reply(StopResult.ACK, StopMode.PAUSED, True, EPOCH, bytes.fromhex("010102030405060708090a0b0c0d0e0f"))
    with pytest.raises(ValueError):
        verify_reply_for(request, other_id)
    other_epoch = encode_reply(StopResult.ACK, StopMode.PAUSED, True, EPOCH + 1, CORRELATION)
    with pytest.raises(ValueError):
        verify_reply_for(request, other_epoch)
    stale = encode_reply(StopResult.STALE_RUNTIME, StopMode.DISARMED, False, EPOCH + 1, CORRELATION)
    with pytest.raises(ValueError):
        verify_reply_for(request, stale)


def test_mismatched_or_weaker_ack_does_not_confirm_requested_stop():
    from gym.contracts.stop_wire import verify_reply_for

    request = encode_request(StopCommand.HALT, EPOCH, CORRELATION)
    fake_ack = encode_reply(StopResult.ACK, StopMode.PAUSED, True, EPOCH, CORRELATION)
    with pytest.raises(ValueError):
        verify_reply_for(request, fake_ack)
