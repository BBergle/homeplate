from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import auth, me, mealie, today

app = FastAPI()
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

