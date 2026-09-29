import argparse
import asyncio
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web
from packaging.version import Version
from uiprotect import ProtectApiClient
from yarl import URL

from unifi import main


@pytest.mark.parametrize("login_status", [200, 403])
def test_token_fetch_with_real_protect_client(monkeypatch, login_status):
    """Exercise real login, token transport and cleanup, without NVR model fixtures."""

    async def scenario():
        calls = []

        async def login(request):
            calls.append("login")
            data = await request.json()
            assert data["username"] == "test-user"
            assert data["password"] == "test-password"
            return web.json_response({}, status=login_status)

        async def token(_request):
            calls.append("token")
            return web.json_response({"mgmt": {"token": "test-adoption-token"}})

        app = web.Application()
        app.router.add_post("/api/auth/login", login)
        app.router.add_get("/proxy/protect/api/cameras/manage-payload", token)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        clients = []

        def client_factory(*args, **kwargs):
            client = ProtectApiClient(
                *args, **kwargs, store_sessions=False, override_connection_host=True
            )
            client._url = URL(f"http://127.0.0.1:{port}")
            clients.append(client)
            return client

        async def bootstrap(_self):
            return SimpleNamespace(nvr=SimpleNamespace(version=Version("1.0.0")))

        monkeypatch.setattr(main, "ProtectApiClient", client_factory)
        monkeypatch.setattr(ProtectApiClient, "get_bootstrap", bootstrap)
        args = argparse.Namespace(
            host="protect.example.invalid",
            nvr_username="test-user",
            nvr_password="test-password",
        )
        try:
            result = await main.generate_token(args, logging.getLogger("test"))
            if login_status == 200:
                assert result == "test-adoption-token"
                assert calls == ["login", "token"]
            else:
                assert result is None
                assert calls == ["login"]
            assert len(clients) == 1
            assert clients[0]._session is None or clients[0]._session.closed
        finally:
            for client in clients:
                await client.close_session()
            await runner.cleanup()

    asyncio.run(scenario())
