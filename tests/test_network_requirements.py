import argparse
import asyncio
import json
import logging
from pathlib import Path

import websockets
from aiohttp import web

from unifi.cams.base import UnifiCamBase
from unifi.cams.rtsp import RTSPCam
from unifi.core import Core


class DummySSLContext:
    def __init__(self):
        self.check_hostname = True
        self.verify_mode = None

    def load_cert_chain(self, *_args, **_kwargs):
        return None


class SnapshotCam(UnifiCamBase):
    async def get_snapshot(self) -> Path:
        return Path(self.args.snapshot_file)

    async def get_stream_source(self, _stream_index: str) -> str:
        return "rtsp://example.invalid/stream"


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


def test_fetch_to_file_uses_real_aiohttp_request(monkeypatch, tmp_path):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    async def scenario():
        async def handle(_request):
            return web.Response(body=b"snapshot-data", content_type="image/jpeg")

        app = web.Application()
        app.router.add_get("/snapshot.jpg", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        cam = SnapshotCam(
            base_args(snapshot_file=str(tmp_path / "unused.jpg")),
            logging.getLogger("test"),
        )
        dst = tmp_path / "snapshot.jpg"
        ok = await cam.fetch_to_file(f"http://127.0.0.1:{port}/snapshot.jpg", dst)

        await runner.cleanup()

        assert ok is True
        assert dst.read_bytes() == b"snapshot-data"

    asyncio.run(scenario())


def test_process_snapshot_request_uploads_snapshot_over_real_aiohttp(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    async def scenario():
        uploads = {}

        async def upload_handler(request):
            reader = await request.post()
            uploads["payload"] = reader["payload"].file.read()
            uploads["token"] = reader["token"]
            return web.Response(text="ok")

        app = web.Application()
        app.router.add_post("/upload", upload_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        snapshot_file = tmp_path / "snapshot.jpg"
        snapshot_file.write_bytes(b"camera-snapshot")
        cam = SnapshotCam(
            base_args(snapshot_file=str(snapshot_file)), logging.getLogger("test")
        )
        cam._ssl_context = False

        response = await cam.process_snapshot_request(
            {
                "messageId": 8,
                "responseExpected": True,
                "payload": {
                    "what": "snapshot",
                    "uri": f"http://127.0.0.1:{port}/upload",
                    "formFields": {"token": "upload-token"},
                },
            }
        )

        await runner.cleanup()

        assert uploads == {
            "payload": b"camera-snapshot",
            "token": "upload-token",
        }
        assert response["functionName"] == "GetRequest"
        assert response["inResponseTo"] == 8

    asyncio.run(scenario())


def test_core_rtsp_smoke_uses_real_websocket_messages(monkeypatch):
    monkeypatch.setattr("ssl.create_default_context", lambda: DummySSLContext())

    async def scenario():
        received = {}
        server_done = asyncio.Event()

        async def handler(websocket):
            hello = json.loads(await websocket.recv())
            received["hello"] = hello

            await websocket.send(
                json.dumps(
                    {
                        "functionName": "ubnt_avclient_paramAgreement",
                        "messageId": 2,
                        "payload": {},
                        "responseExpected": True,
                    }
                )
            )
            received["param_agreement"] = json.loads(await websocket.recv())

            await websocket.send(
                json.dumps(
                    {
                        "functionName": "ChangeVideoSettings",
                        "messageId": 3,
                        "payload": None,
                        "responseExpected": True,
                    }
                )
            )
            received["video_settings"] = json.loads(await websocket.recv())
            await websocket.send(
                json.dumps(
                    {
                        "functionName": "Reboot",
                        "messageId": 4,
                        "payload": {},
                        "responseExpected": False,
                    }
                )
            )
            server_done.set()

        server = await websockets.serve(
            handler, "127.0.0.1", 0, subprotocols=["secure_transfer"]
        )
        port = server.sockets[0].getsockname()[1]

        real_connect = websockets.connect

        def test_connect(_uri, **kwargs):
            kwargs.pop("ssl", None)
            return real_connect(f"ws://127.0.0.1:{port}", **kwargs)

        monkeypatch.setattr("unifi.core.websockets.connect", test_connect)

        args = base_args(
            host="127.0.0.1",
            token="adoption-token",
            mac="AA:BB:CC:DD:EE:FF",
            source=["rtsp://example.invalid/high"],
            snapshot_url="http://example.invalid/snapshot.jpg",
            http_api=0,
        )
        cam = RTSPCam(args, logging.getLogger("test"))
        monkeypatch.setattr(
            cam,
            "probe_stream_dimensions",
            lambda stream_index, _source: {"width": 1920, "height": 1080}
            if stream_index == "video1"
            else {"width": 1280, "height": 720}
            if stream_index == "video2"
            else {"width": 640, "height": 360},
        )
        core = Core(args, cam, logging.getLogger("test"))

        await core.run()
        await asyncio.wait_for(server_done.wait(), timeout=2)

        server.close()
        await server.wait_closed()

        assert received["hello"]["functionName"] == "ubnt_avclient_hello"
        assert received["hello"]["payload"]["adoptionCode"] == "adoption-token"
        assert received["hello"]["payload"]["mac"] == "AA:BB:CC:DD:EE:FF"
        assert received["param_agreement"]["payload"]["authToken"] == "adoption-token"
        assert received["video_settings"]["functionName"] == "ChangeVideoSettings"
        assert (
            received["video_settings"]["payload"]["video"]["video1"]["enabled"] is True
        )

    asyncio.run(scenario())
