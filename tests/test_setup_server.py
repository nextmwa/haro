from aiohttp.test_utils import TestClient, TestServer

from haro.setup_server import create_setup_app


async def test_index_lists_networks():
    app = create_setup_app(["HomeWifi", "Office"], on_submit=None)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        text = await resp.text()

    assert resp.status == 200
    assert "HomeWifi" in text
    assert "Office" in text


async def test_connect_calls_on_submit_and_reports_success():
    calls: list[tuple[str, str]] = []

    async def on_submit(ssid: str, password: str) -> bool:
        calls.append((ssid, password))
        return True

    app = create_setup_app(["HomeWifi"], on_submit=on_submit)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/connect", data={"ssid": "HomeWifi", "password": "secret"})

    assert resp.status == 200
    assert calls == [("HomeWifi", "secret")]


async def test_connect_reports_failure_from_on_submit():
    async def on_submit(ssid: str, password: str) -> bool:
        return False

    app = create_setup_app(["HomeWifi"], on_submit=on_submit)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/connect", data={"ssid": "HomeWifi", "password": "wrong"})

    assert resp.status == 400


async def test_connect_without_ssid_returns_400():
    app = create_setup_app([], on_submit=None)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/connect", data={"password": "secret"})

    assert resp.status == 400
