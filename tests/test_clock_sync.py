import argparse
import io
import struct
from types import SimpleNamespace

import pytest

from unifi import clock_sync


@pytest.mark.parametrize("flags", [1, 4, 5])
def test_stream_header_preserves_media_tracks(monkeypatch, flags):
    source = b"FLV\x01" + bytes([flags]) + struct.pack(">II", 9, 0)
    output = io.BytesIO()
    monkeypatch.setattr(
        clock_sync.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(source))
    )
    monkeypatch.setattr(clock_sync.sys, "stdout", SimpleNamespace(buffer=output))

    clock_sync.main(argparse.Namespace(timestamp_modifier=90))

    assert output.getvalue() == source[:4] + bytes([flags | 2]) + source[5:]


@pytest.mark.parametrize("is_video,timebase", [(True, 90000), (False, 11025)])
@pytest.mark.parametrize("ticks", [0, 90000, 2**32 - 1, 2**32, 2**32 + 90000])
def test_timestamp_extension_retains_full_counter(
    monkeypatch, is_video, timebase, ticks
):
    output = io.BytesIO()
    monkeypatch.setattr(clock_sync, "write", output.write)

    clock_sync.write_timestamp_trailer(is_video, ticks / 1000)

    assert output.getvalue() == struct.pack(">IIQ", timebase, 0, ticks)


@pytest.mark.parametrize("is_video", [True, False])
def test_timestamp_extension_matches_existing_format_before_rollover(
    monkeypatch, is_video
):
    output = io.BytesIO()
    monkeypatch.setattr(clock_sync, "write", output.write)

    clock_sync.write_timestamp_trailer(is_video, 1234.5)

    timebase = b"\x00\x01\x5f\x90" if is_video else b"\x00\x00\x2b\x11"
    assert output.getvalue() == timebase + bytes(8) + struct.pack(">I", 1234500)
