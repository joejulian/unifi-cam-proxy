import argparse
import asyncio
import logging
import sys

import pytest

from unifi import main as unifi_main


def test_parse_args_accepts_documented_rtsp_invocation(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "unifi-cam-proxy",
            "--host",
            "protect.example",
            "--cert",
            "/client.pem",
            "--token",
            "adoption-token",
            "rtsp",
            "--source",
            "rtsp://camera.example/high",
        ],
    )

    args = unifi_main.parse_args()

    assert args.host == "protect.example"
    assert args.cert == "/client.pem"
    assert args.token == "adoption-token"
    assert args.impl == "rtsp"
    assert args.source == ["rtsp://camera.example/high"]


def test_run_exits_when_ffmpeg_is_missing(monkeypatch):
    args = argparse.Namespace(
        impl="rtsp",
        verbose=False,
        token="adoption-token",
        host="protect.example",
    )
    monkeypatch.setattr(unifi_main, "parse_args", lambda: args)
    monkeypatch.setattr(unifi_main.coloredlogs, "install", lambda **_kwargs: None)
    monkeypatch.setattr(
        unifi_main,
        "which",
        lambda binary: None if binary == "ffmpeg" else "/usr/bin/nc",
    )

    with pytest.raises(SystemExit):
        asyncio.run(unifi_main.run())


def test_run_exits_when_no_adoption_token_is_available(monkeypatch):
    args = argparse.Namespace(
        impl="rtsp",
        verbose=False,
        token=None,
        host="protect.example",
    )

    class FakeCam:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("camera should not be constructed without a token")

    monkeypatch.setattr(unifi_main, "parse_args", lambda: args)
    monkeypatch.setattr(unifi_main.coloredlogs, "install", lambda **_kwargs: None)
    monkeypatch.setattr(unifi_main, "which", lambda _binary: "/usr/bin/present")

    async def fake_generate_token(*_args, **_kwargs):
        return None

    monkeypatch.setattr(unifi_main, "generate_token", fake_generate_token)
    monkeypatch.setitem(unifi_main.CAMS, "rtsp", FakeCam)

    with pytest.raises(SystemExit):
        asyncio.run(unifi_main.run())


def test_generate_token_returns_manage_payload_token_and_closes_session(monkeypatch):
    closed = False

    class FakeProtectApiClient:
        def __init__(self, host, port, username, password, verify_ssl):
            assert host == "protect.example"
            assert port == 443
            assert username == "user"
            assert password == "pass"
            assert verify_ssl is False

        async def update(self):
            return None

        async def api_request(self, path):
            assert path == "cameras/manage-payload"
            return {"mgmt": {"token": "generated-token"}}

        async def close_session(self):
            nonlocal closed
            closed = True

    args = argparse.Namespace(
        host="protect.example",
        nvr_username="user",
        nvr_password="pass",
    )
    monkeypatch.setattr(unifi_main, "ProtectApiClient", FakeProtectApiClient)

    token = asyncio.run(unifi_main.generate_token(args, logging.getLogger("test")))

    assert token == "generated-token"
    assert closed is True


def test_generate_token_returns_none_when_client_creation_fails(monkeypatch, caplog):
    class FakeProtectApiClient:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("cannot connect")

    args = argparse.Namespace(
        host="protect.example",
        nvr_username="user",
        nvr_password="pass",
    )
    monkeypatch.setattr(unifi_main, "ProtectApiClient", FakeProtectApiClient)

    with caplog.at_level(logging.ERROR):
        token = asyncio.run(unifi_main.generate_token(args, logging.getLogger("test")))

    assert token is None
    assert "Could not automatically fetch token" in caplog.text


def test_generate_token_returns_none_when_manage_payload_fails_and_closes_session(
    monkeypatch, caplog
):
    closed = False

    class FakeProtectApiClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def update(self):
            return None

        async def api_request(self, path):
            assert path == "cameras/manage-payload"
            raise RuntimeError("request failed")

        async def close_session(self):
            nonlocal closed
            closed = True

    args = argparse.Namespace(
        host="protect.example",
        nvr_username="user",
        nvr_password="pass",
    )
    monkeypatch.setattr(unifi_main, "ProtectApiClient", FakeProtectApiClient)

    with caplog.at_level(logging.ERROR):
        token = asyncio.run(unifi_main.generate_token(args, logging.getLogger("test")))

    assert token is None
    assert closed is True
    assert "Could not automatically fetch token" in caplog.text
