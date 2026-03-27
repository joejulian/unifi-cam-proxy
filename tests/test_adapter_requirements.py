import argparse
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from unifi.cams.base import RetryableError, SmartDetectObjectType
from unifi.cams.dahua import DahuaCam
from unifi.cams.frigate import FrigateCam
from unifi.cams.hikvision import HikvisionCam
from unifi.cams.reolink import Reolink
from unifi.cams.reolink_nvr import ReolinkNVRCam
from unifi.cams.tapo import TapoCam


class DummySSLContext:
    def __init__(self):
        self.check_hostname = True
        self.verify_mode = None

    def load_cert_chain(self, *_args, **_kwargs):
        return None


def base_args(**overrides):
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
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_dahua_uses_main_and_sub_stream_profiles(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    class FakeDevice:
        async def async_rtsp_url(self, channel, typeno):
            return f"rtsp://camera/ch{channel}/type{typeno}"

    class FakeAmcrestCamera:
        def __init__(self, *_args, **_kwargs):
            self.camera = FakeDevice()

    monkeypatch.setattr("unifi.cams.dahua.AmcrestCamera", FakeAmcrestCamera)

    cam = DahuaCam(
        base_args(
            username="user",
            password="pass",
            channel=7,
            snapshot_channel=None,
            motion_index=None,
            main_stream=4,
            sub_stream=9,
            ptz=True,
        ),
        logging.getLogger("test"),
    )

    assert cam.args.snapshot_channel == 6
    assert cam.args.motion_index == 6
    assert asyncio.run(cam.get_stream_source("video1")) == "rtsp://camera/ch7/type4"
    assert asyncio.run(cam.get_stream_source("video2")) == "rtsp://camera/ch7/type9"
    assert asyncio.run(cam.get_feature_flags())["ptz"] is True


def test_dahua_raises_retryable_error_when_rtsp_url_cannot_be_built(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    class FakeCommError(Exception):
        pass

    class FakeDevice:
        async def async_rtsp_url(self, *_args, **_kwargs):
            raise FakeCommError("boom")

    class FakeAmcrestCamera:
        def __init__(self, *_args, **_kwargs):
            self.camera = FakeDevice()

    monkeypatch.setattr("unifi.cams.dahua.CommError", FakeCommError)
    monkeypatch.setattr("unifi.cams.dahua.AmcrestCamera", FakeAmcrestCamera)

    cam = DahuaCam(
        base_args(
            username="user",
            password="pass",
            channel=1,
            snapshot_channel=0,
            motion_index=0,
            main_stream=0,
            sub_stream=1,
            ptz=False,
        ),
        logging.getLogger("test"),
    )

    with pytest.raises(RetryableError):
        asyncio.run(cam.get_stream_source("video1"))


def test_frigate_detection_waits_for_matching_snapshot_before_ending(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    cam = FrigateCam(
        base_args(
            source=["rtsp://example.invalid/high"],
            snapshot_url="http://example.invalid/snapshot.jpg",
            http_api=0,
            mqtt_host="mqtt.example",
            mqtt_port=1883,
            mqtt_username=None,
            mqtt_password=None,
            mqtt_prefix="frigate",
            frigate_camera="front-door",
        ),
        logging.getLogger("test"),
    )

    calls = []

    async def fake_start(object_type=None):
        calls.append(("start", object_type))

    async def fake_stop():
        calls.append(("stop", None))

    monkeypatch.setattr(cam, "trigger_motion_start", fake_start)
    monkeypatch.setattr(cam, "trigger_motion_stop", fake_stop)

    class Topic:
        def __init__(self, value):
            self.value = value

        def matches(self, pattern):
            return self.value == pattern.replace("#", "events")

    new_message = SimpleNamespace(
        topic=Topic("frigate/events"),
        payload=json.dumps(
            {
                "type": "new",
                "after": {
                    "camera": "front-door",
                    "id": "event-1",
                    "label": "person",
                },
            }
        ).encode(),
        retain=False,
    )
    snapshot_message = SimpleNamespace(
        topic=SimpleNamespace(value="frigate/front-door/person/snapshot"),
        payload=b"snapshot-bytes",
        retain=False,
    )
    end_message = SimpleNamespace(
        topic=Topic("frigate/events"),
        payload=json.dumps(
            {
                "type": "end",
                "after": {
                    "camera": "front-door",
                    "id": "event-1",
                    "label": "person",
                },
            }
        ).encode(),
        retain=False,
    )

    asyncio.run(cam.handle_detection_event(new_message))
    asyncio.run(cam.handle_snapshot_event(snapshot_message))
    asyncio.run(cam.handle_detection_event(end_message))

    assert calls == [
        ("start", SmartDetectObjectType.PERSON),
        ("stop", None),
    ]
    assert cam.event_id is None
    assert cam.event_label is None


def test_hikvision_uses_primary_stream_for_video1_and_substream_for_lower_qualities(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            self.PTZCtrl = SimpleNamespace(
                channels={
                    5: SimpleNamespace(
                        capabilities=lambda **_kwargs: None,
                    )
                }
            )

    monkeypatch.setattr("unifi.cams.hikvision.AsyncClient", FakeAsyncClient)

    cam = HikvisionCam(
        base_args(username="user", password="pass", channel=5, substream=7),
        logging.getLogger("test"),
    )

    assert (
        asyncio.run(cam.get_stream_source("video1"))
        == "rtsp://user:pass@192.0.2.10:554/Streaming/Channels/501/"
    )
    assert (
        asyncio.run(cam.get_stream_source("video2"))
        == "rtsp://user:pass@192.0.2.10:554/Streaming/Channels/507/"
    )


def test_reolink_builds_snapshot_and_stream_urls_from_config(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    class FakeCamera:
        def __init__(self, **_kwargs):
            pass

        def get_recording_encoding(self):
            return [
                {
                    "value": {
                        "Enc": {
                            "mainStream": {"frameRate": 25},
                            "subStream": {"frameRate": 12},
                        }
                    }
                }
            ]

    monkeypatch.setattr("unifi.cams.reolink.reolinkapi.Camera", FakeCamera)

    cam = Reolink(
        base_args(
            username="user",
            password="pass",
            channel=0,
            stream="main",
            substream="sub",
        ),
        logging.getLogger("test"),
    )

    assert (
        asyncio.run(cam.get_stream_source("video1"))
        == "rtsp://user:pass@192.0.2.10:554//h264Preview_01_main"
    )
    assert (
        asyncio.run(cam.get_stream_source("video3"))
        == "rtsp://user:pass@192.0.2.10:554//h264Preview_01_sub"
    )
    assert "tick_rate=50" in cam.get_extra_ffmpeg_args("video1")
    assert "tick_rate=24" in cam.get_extra_ffmpeg_args("video2")


def test_reolink_nvr_uses_channel_for_snapshot_and_rtsp_urls(monkeypatch, tmp_path):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    cam = ReolinkNVRCam(
        base_args(username="user", password="pass", channel="3"),
        logging.getLogger("test"),
    )
    img_file = tmp_path / "screen.jpg"
    cam.snapshot_dir = str(tmp_path)
    captured = {}

    async def fake_fetch(url, dst):
        captured["url"] = url
        captured["dst"] = dst
        dst.write_bytes(b"image")
        return True

    monkeypatch.setattr(cam, "fetch_to_file", fake_fetch)

    path = asyncio.run(cam.get_snapshot())

    assert path == img_file
    assert "channel=3" in captured["url"]
    assert asyncio.run(cam.get_stream_source("video1")) == (
        "rtsp://user:pass@192.0.2.10:554/h264Preview_04_main"
    )


def test_tapo_maps_streams_and_detects_ptz_capability(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    class FakeTapo:
        def __init__(self, *_args, **_kwargs):
            pass

        def getMotorCapability(self):
            return {"capability": "ptz"}

    monkeypatch.setattr("unifi.cams.tapo.Tapo", FakeTapo)

    cam = TapoCam(
        base_args(
            username="user",
            password="pass",
            rtsp="rtsp://camera-base",
            snapshot_url="http://example.invalid/current.jpg",
            http_api=0,
        ),
        logging.getLogger("test"),
    )

    assert cam.ptz_enabled is True
    assert asyncio.run(cam.get_stream_source("video1")) == "rtsp://camera-base/stream1"
    assert asyncio.run(cam.get_stream_source("video2")) == "rtsp://camera-base/stream1"
    assert asyncio.run(cam.get_stream_source("video3")) == "rtsp://camera-base/stream2"
