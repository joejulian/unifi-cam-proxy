import argparse
import asyncio
import json
import logging
import subprocess
from pathlib import Path

from unifi.cams.rtsp import RTSPCam


class DummySSLContext:
    def __init__(self):
        self.check_hostname = True
        self.verify_mode = None

    def load_cert_chain(self, *_args, **_kwargs):
        return None


def build_args(**overrides):
    args = argparse.Namespace(
        cert="/tmp/client.pem",
        ffmpeg_args="-c copy",
        ffmpeg_base_args=None,
        rtsp_transport="tcp",
        timestamp_modifier=90,
        loglevel="error",
        format="flv",
        token="token",
        mac="AA:BB:CC:DD:EE:FF",
        host="protect.example",
        fw_version="test",
        ip="192.0.2.10",
        model="UVC G3",
        name="camera",
        source=["rtsp://example.invalid/high"],
        http_api=0,
        snapshot_url="http://example.invalid/snapshot.jpg",
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_rtsp_single_source_is_used_for_all_video_streams(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    cam = RTSPCam(build_args(), logging.getLogger("test"))

    assert asyncio.run(cam.get_stream_source("video1")) == "rtsp://example.invalid/high"
    assert asyncio.run(cam.get_stream_source("video2")) == "rtsp://example.invalid/high"
    assert asyncio.run(cam.get_stream_source("video3")) == "rtsp://example.invalid/high"


def test_rtsp_two_sources_map_in_descending_quality_order(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    cam = RTSPCam(
        build_args(
            source=[
                "rtsp://example.invalid/high",
                "rtsp://example.invalid/medium",
            ]
        ),
        logging.getLogger("test"),
    )

    assert asyncio.run(cam.get_stream_source("video1")) == "rtsp://example.invalid/high"
    assert (
        asyncio.run(cam.get_stream_source("video2")) == "rtsp://example.invalid/medium"
    )
    assert (
        asyncio.run(cam.get_stream_source("video3")) == "rtsp://example.invalid/medium"
    )


def test_snapshot_url_is_used_for_snapshots(monkeypatch, tmp_path):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())
    cam = RTSPCam(
        build_args(snapshot_url="http://example.invalid/current.jpg"),
        logging.getLogger("test"),
    )

    fetched = {}

    async def fake_fetch(url, dst):
        fetched["url"] = url
        fetched["dst"] = dst
        dst.write_bytes(b"snapshot")
        return True

    cam.snapshot_dir = str(tmp_path)
    monkeypatch.setattr(cam, "fetch_to_file", fake_fetch)

    path = asyncio.run(cam.get_snapshot())

    assert path == Path(tmp_path, "screen.jpg")
    assert fetched == {
        "url": "http://example.invalid/current.jpg",
        "dst": Path(tmp_path, "screen.jpg"),
    }
    assert path.read_bytes() == b"snapshot"


def test_rtsp_cam_probes_dimensions_per_configured_stream(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    calls = []

    def fake_check_output(cmd):
        source = cmd[-1]
        calls.append(source)
        dimensions = {
            "rtsp://example.invalid/high": {"width": 1280, "height": 960},
            "rtsp://example.invalid/medium": {"width": 640, "height": 480},
            "rtsp://example.invalid/low": {"width": 352, "height": 240},
        }[source]
        return json.dumps({"streams": [dimensions]}).encode()

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    cam = RTSPCam(
        build_args(
            source=[
                "rtsp://example.invalid/high",
                "rtsp://example.invalid/medium",
                "rtsp://example.invalid/low",
            ]
        ),
        logging.getLogger("test"),
    )

    assert cam.get_stream_dimensions("video1") == {"width": 1280, "height": 960}
    assert cam.get_stream_dimensions("video2") == {"width": 640, "height": 480}
    assert cam.get_stream_dimensions("video3") == {"width": 352, "height": 240}
    assert cam.get_stream_dimensions("mjpg") == {"width": 1280, "height": 960}
    assert calls == [
        "rtsp://example.invalid/high",
        "rtsp://example.invalid/medium",
        "rtsp://example.invalid/low",
    ]


def test_rtsp_dimension_probe_falls_back_to_safe_defaults(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    def fake_check_output(_cmd):
        raise subprocess.CalledProcessError(returncode=1, cmd="ffprobe")

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    cam = RTSPCam(
        build_args(
            source=[
                "rtsp://example.invalid/high",
                "rtsp://example.invalid/medium",
                "rtsp://example.invalid/low",
            ]
        ),
        logging.getLogger("test"),
    )

    assert cam.get_stream_dimensions("video1") == {"width": 1920, "height": 1080}
    assert cam.get_stream_dimensions("video2") == {"width": 1280, "height": 720}
    assert cam.get_stream_dimensions("video3") == {"width": 640, "height": 360}
