from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app import auth, me, mealie, today

MAX_BODY = 20 * 1024 * 1024


class _TooBig(Exception):
    pass


class BodyLimit:
    """Reject request bodies over MAX_BODY (413) before anything parses them."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rejected = False
        seen = 0

        async def reject():
            nonlocal rejected
            if not rejected:
                rejected = True
                await Response("Request body too large", 413)(scope, receive, send)
            raise _TooBig

        async def counting_receive():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > MAX_BODY:
                    await reject()
            return msg

        async def quiet_send(msg):  # the app may try to answer its own error after we did
            if not rejected:
                await send(msg)

        try:
            if int(dict(scope["headers"]).get(b"content-length", 0) or 0) > MAX_BODY:
                await reject()
            await self.app(scope, counting_receive, quiet_send)
        except _TooBig:
            pass


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(BodyLimit)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(auth.router)
app.include_router(today.router)
app.include_router(me.router)


@app.exception_handler(auth.LoginRequired)
@app.exception_handler(mealie.MealieAuthError)
def mealie_auth_error(request: Request, exc):
    return auth.drop_session(request)


@app.exception_handler(mealie.MealieError)
def mealie_error(request: Request, exc):
    if request.headers.get("HX-Request"):
        return HTMLResponse('<p class="error" role="alert">Can\'t reach Mealie</p>')
    return auth.templates.TemplateResponse(request, "error.html", {}, status_code=502)


@app.get("/healthz")
def healthz():
    return {"ok": True}

