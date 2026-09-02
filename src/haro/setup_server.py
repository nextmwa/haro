from typing import Awaitable, Callable

from aiohttp import web

ConnectCallback = Callable[[str, str], Awaitable[bool]]


def create_setup_app(networks: list[str], on_submit: ConnectCallback) -> web.Application:
    app = web.Application()

    async def index(request: web.Request) -> web.Response:
        options = "".join(
            f'<label><input type="radio" name="ssid" value="{ssid}" required> {ssid}</label><br>'
            for ssid in networks
        )
        html = f"""
        <html><body>
        <h1>Haro setup</h1>
        <form method="post" action="/connect">
        {options}
        <label>Password: <input type="password" name="password"></label><br>
        <button type="submit">Connect</button>
        </form>
        </body></html>
        """
        return web.Response(text=html, content_type="text/html")

    async def connect(request: web.Request) -> web.Response:
        data = await request.post()
        ssid = str(data.get("ssid", ""))
        password = str(data.get("password", ""))
        if not ssid:
            return web.Response(text="Missing network selection", status=400)
        success = await on_submit(ssid, password)
        if success:
            return web.Response(text="Connected! Haro is resuming normal operation.")
        return web.Response(text="Could not connect. Go back and try again.", status=400)

    app.router.add_get("/", index)
    app.router.add_post("/connect", connect)
    return app
