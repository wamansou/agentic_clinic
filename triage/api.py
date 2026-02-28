"""FastAPI application: REST routes, WebSocket, and static file serving."""

import json
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from triage.config import PROJECT_DIR, DB_DIR
from triage.auth import login_required, handle_login, handle_logout, get_current_user
from triage.session_store import SessionStore
from triage.orchestrator import run_agent_turn


# =============================================================================
# App Setup
# =============================================================================

app = FastAPI(title="Kvinde Klinikken Triage", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(PROJECT_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(PROJECT_DIR / "templates"))

store = SessionStore(DB_DIR / "dashboard.db")


# =============================================================================
# Auth Middleware
# =============================================================================

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user = login_required(request)
        if user is None:
            if request.url.path.startswith("/api/") or request.url.path.startswith("/ws/"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        request.state.user = user
        return await call_next(request)


app.add_middleware(AuthMiddleware)


# =============================================================================
# Page Routes
# =============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    response = RedirectResponse("/", status_code=303)
    if handle_login(username, password, response):
        return response
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Invalid credentials"}, status_code=401
    )


@app.post("/logout")
async def logout(request: Request):
    response = RedirectResponse("/login", status_code=303)
    handle_logout(response)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    user = get_current_user(request)
    sessions = store.list_sessions()
    return templates.TemplateResponse("history.html", {
        "request": request,
        "user": user,
        "sessions": sessions,
    })


# =============================================================================
# API Routes
# =============================================================================

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/sessions")
async def api_list_sessions():
    return store.list_sessions()


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    session = store.get_session(session_id)
    if not session:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "not found"}, status_code=404)
    result = store.get_result(session_id)
    session["result"] = result
    return session


@app.post("/api/sessions")
async def api_create_session():
    session_id = f"demo_{uuid.uuid4().hex[:8]}"
    meta = store.create_session(session_id)
    return {"session_id": meta.session_id, "created_at": meta.created_at.isoformat()}


@app.delete("/api/sessions/inactive")
async def api_delete_inactive():
    count = store.delete_inactive()
    return {"deleted": count}


# =============================================================================
# WebSocket
# =============================================================================

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    # Ensure session exists in store
    if not store.get_session(session_id):
        store.create_session(session_id)

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") != "chat":
                continue

            message = data.get("data", {}).get("message", "").strip()
            if not message:
                continue

            # Send thinking indicator
            await websocket.send_json({"type": "status", "data": {"state": "thinking"}})

            try:
                result = await run_agent_turn(session_id, message)
            except Exception as e:
                await websocket.send_json({
                    "type": "chat",
                    "data": {"message": f"Sorry, an error occurred: {str(e)}"},
                })
                continue

            # Send partial triage updates
            if result.get("partial"):
                await websocket.send_json({
                    "type": "triage_update",
                    "data": result["partial"],
                })

            if result["type"] == "text":
                # Ongoing conversation
                await websocket.send_json({
                    "type": "chat",
                    "data": {"message": result["content"]},
                })
            else:
                # Triage complete — update session store
                triage_data = result.get("triage_data", {})
                result_data = result.get("result", {})
                is_handoff = result["type"] == "handoff"

                store.update_session(
                    session_id,
                    patient_name=triage_data.get("patient_name"),
                    status="escalated" if is_handoff else "completed",
                    condition_name=triage_data.get("condition_name"),
                    result_type=result["type"],
                )
                store.save_result(session_id, json.dumps(result_data))

                # Send triage update with all fields
                await websocket.send_json({
                    "type": "triage_update",
                    "data": triage_data,
                })

                # Send completion
                await websocket.send_json({
                    "type": "complete",
                    "data": {
                        "result_type": result["type"],
                        "result": result_data,
                        "confirmation": result["content"],
                    },
                })

            # Update patient name if available from partial data
            if result.get("partial", {}).get("condition_name") or result.get("triage_data", {}).get("patient_name"):
                partial = result.get("partial", {})
                triage = result.get("triage_data", {})
                store.update_session(
                    session_id,
                    patient_name=triage.get("patient_name") or None,
                    condition_name=partial.get("condition_name") or triage.get("condition_name") or None,
                )

    except WebSocketDisconnect:
        pass
