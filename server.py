"""PhoneAgent web server."""

import asyncio
import datetime
import json
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Load local .env file if it exists
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as env_file:
        for line in env_file:
            if line.strip() and not line.strip().startswith("#"):
                key, value = line.strip().split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

from phoneagent.agent import PhoneAgent
from phoneagent.companion import CompanionController, DeviceSessionManager

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: dict[str, WebSocket] = {}
agent_instances: dict[str, PhoneAgent] = {}
device_session_manager = DeviceSessionManager(
    auth_token=os.environ.get("DEVICE_BRIDGE_TOKEN", ""),
)

DEVICE_MODE = os.environ.get("DEVICE_MODE", "local").strip().lower() or "local"
DEVICE_ID = os.environ.get("DEVICE_ID", "phoneagent-device")
PHONEAGENT_DB_PATH = os.environ.get("PHONEAGENT_DB_PATH")
APP_PORT = int(os.environ.get("PORT", os.environ.get("APP_PORT", "8000")))
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"


class PaletteRequest(BaseModel):
    prompt: str


async def broadcast_to_session(session_id: str, message: dict):
    websocket = active_connections.get(session_id)
    if websocket:
        try:
            await websocket.send_json(message)
        except Exception as exc:
            print(f"Error broadcasting to {session_id}: {exc}")


def create_controller():
    if DEVICE_MODE == "companion":
        return CompanionController(
            manager=device_session_manager,
            device_id=DEVICE_ID,
            request_timeout=float(os.environ.get("DEVICE_RPC_TIMEOUT", "20")),
        )
    return None


def build_agent(session_id: str, loop: asyncio.AbstractEventLoop) -> PhoneAgent:
    def threadsafe_status(msg):
        asyncio.run_coroutine_threadsafe(
            broadcast_to_session(session_id, {"type": "status", "message": msg}),
            loop,
        )

    def threadsafe_tool_call(name, args):
        asyncio.run_coroutine_threadsafe(
            broadcast_to_session(session_id, {"type": "tool_call", "name": name, "args": args}),
            loop,
        )

    def threadsafe_tool_result(name, result):
        clean_res = result.copy()
        clean_res.pop("image", None)
        asyncio.run_coroutine_threadsafe(
            broadcast_to_session(session_id, {"type": "tool_result", "name": name, "result": clean_res}),
            loop,
        )

    return PhoneAgent(
        api_key=os.environ.get("GROQ_API_KEY"),
        db_path=PHONEAGENT_DB_PATH,
        controller=create_controller(),
        on_status=threadsafe_status,
        on_tool_call=threadsafe_tool_call,
        on_tool_result=threadsafe_tool_result,
    )


def build_device_payload(agent: PhoneAgent) -> dict:
    info = agent.get_device_info() if agent.is_device_connected() else {}
    info = dict(info)
    info["online"] = agent.is_device_connected()
    info["controller_mode"] = agent.controller.mode
    info["capabilities"] = agent.get_device_capabilities()
    info.setdefault("model", "Device" if info["online"] else "No device connected")
    return info


def _generate_greeting() -> str:
    try:
        import importlib.util

        greet_path = os.path.join(os.path.dirname(__file__), "greet.py")
        spec = importlib.util.spec_from_file_location("greet", greet_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load greet.py module")
        greet_mod = importlib.util.module_from_spec(spec)

        original_cwd = os.getcwd()
        os.chdir(os.path.dirname(__file__))
        spec.loader.exec_module(greet_mod)

        model, c2i, i2c = greet_mod.load_model()
        now = datetime.datetime.now()
        hour_float = now.hour + now.minute / 60.0
        phrase = model.generate(hour_float, c2i, i2c)
        os.chdir(original_cwd)
        return phrase.strip()
    except Exception as exc:
        print(f"Greeting model error: {exc}")
        return "Welcome"


def _generate_palette_with_kimi(prompt: str) -> dict:
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key)
    system_prompt = """You are a world-class UI color palette designer. Given a mood or phrase, generate a beautiful, harmonious color palette for a modern application UI. Return ONLY valid JSON for the requested CSS variables."""

    completion = client.chat.completions.create(
        model="moonshotai/kimi-k2-instruct-0905",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate a color palette for: \"{prompt}\""},
        ],
        temperature=0.8,
        max_completion_tokens=1024,
        top_p=1,
    )

    response_text = completion.choices[0].message.content or ""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


@app.post("/api/generate-palette")
async def generate_palette(req: PaletteRequest):
    try:
        palette = await asyncio.to_thread(lambda: _generate_palette_with_kimi(req.prompt))
        return {"palette": palette}
    except Exception as exc:
        print(f"Palette generation error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/greeting")
async def get_greeting():
    try:
        greeting = await asyncio.to_thread(lambda: _generate_greeting())
        return {"greeting": greeting}
    except Exception as exc:
        return {"greeting": "Welcome", "error": str(exc)}


@app.get("/api/runtime")
async def get_runtime():
    return {
        "device_mode": DEVICE_MODE,
        "device_id": DEVICE_ID,
        "device_online": device_session_manager.is_connected(DEVICE_ID) if DEVICE_MODE == "companion" else None,
        "db_path": PHONEAGENT_DB_PATH,
    }


@app.websocket("/ws/device/{device_id}")
async def device_websocket(websocket: WebSocket, device_id: str):
    await websocket.accept()
    loop = asyncio.get_running_loop()
    registered = False
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if hello.get("type") != "hello":
            await websocket.send_json({"type": "auth_error", "message": "Expected hello handshake first."})
            await websocket.close(code=1008)
            return
        if device_id != DEVICE_ID:
            await websocket.send_json({"type": "auth_error", "message": "Unexpected device id."})
            await websocket.close(code=1008)
            return
        if not device_session_manager.verify_token(str(hello.get("token", ""))):
            await websocket.send_json({"type": "auth_error", "message": "Invalid device token."})
            await websocket.close(code=1008)
            return

        device_session_manager.register_session(
            device_id=device_id,
            websocket=websocket,
            loop=loop,
            capabilities=hello.get("capabilities"),
            device_info=hello.get("device_info"),
            metadata=hello.get("metadata"),
        )
        registered = True
        await websocket.send_json({"type": "hello_ack", "ok": True, "device_id": device_id})

        while True:
            payload = await websocket.receive_json()
            message_type = payload.get("type")
            if message_type == "heartbeat":
                device_session_manager.update_heartbeat(
                    device_id,
                    capabilities=payload.get("capabilities"),
                    device_info=payload.get("device_info"),
                    metadata=payload.get("metadata"),
                )
            elif message_type == "rpc_response":
                device_session_manager.handle_response(device_id, payload)
            elif message_type == "hello":
                device_session_manager.update_heartbeat(
                    device_id,
                    capabilities=payload.get("capabilities"),
                    device_info=payload.get("device_info"),
                    metadata=payload.get("metadata"),
                )
    except WebSocketDisconnect:
        print(f"Device {device_id} disconnected")
    except Exception as exc:
        print(f"Device websocket error: {exc}")
    finally:
        if registered:
            device_session_manager.unregister_session(device_id, websocket)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_connections[session_id] = websocket

    if not os.environ.get("GROQ_API_KEY"):
        await websocket.send_json({
            "type": "system_error",
            "message": "GROQ_API_KEY environment variable not set on server.",
        })
        await websocket.close()
        return

    loop = asyncio.get_running_loop()

    try:
        agent = build_agent(session_id, loop)
        agent_instances[session_id] = agent

        greeting_text = await asyncio.to_thread(lambda: _generate_greeting())
        await websocket.send_json({"type": "greeting", "text": greeting_text})
        await websocket.send_json({"type": "device_info", "info": build_device_payload(agent)})

        while True:
            payload = await websocket.receive_json()
            message_type = payload.get("type")

            if message_type == "user_message":
                user_text = payload.get("message", "")
                response = await asyncio.to_thread(agent.process_message, user_text)
                await websocket.send_json({"type": "agent_message", "message": response})

            elif message_type == "get_device":
                await websocket.send_json({"type": "device_info", "info": build_device_payload(agent)})

            elif message_type == "get_memory":
                await websocket.send_json({"type": "memory_stats", "stats": agent.get_memory_stats()})

            elif message_type == "get_memories":
                await websocket.send_json({"type": "memories_list", "memories": agent.get_all_memories()})

            elif message_type == "get_episodes":
                episodes = agent.get_recent_tasks(20)
                clean_episodes = []
                for episode in episodes:
                    clean_episodes.append({
                        "id": episode.get("id"),
                        "task_description": episode.get("task_description", "")[:120],
                        "result": episode.get("result", "")[:100],
                        "success": episode.get("success", 0),
                        "duration_seconds": episode.get("duration_seconds", 0),
                        "created_at": episode.get("created_at", ""),
                        "metadata": episode.get("metadata", {}),
                    })
                await websocket.send_json({"type": "episodes_list", "episodes": clean_episodes})

            elif message_type == "delete_memory":
                key = payload.get("key")
                if key:
                    agent.memory.forget(key)
                    await websocket.send_json({"type": "memory_deleted", "key": key})

    except WebSocketDisconnect:
        print(f"Client {session_id} disconnected")
    except Exception as exc:
        print(f"WebSocket error: {exc}")
        if session_id in active_connections:
            await active_connections[session_id].send_json({"type": "system_error", "message": str(exc)})
    finally:
        active_connections.pop(session_id, None)
        agent = agent_instances.pop(session_id, None)
        if agent:
            agent.shutdown()


if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if full_path.startswith("api") or full_path.startswith("ws"):
        return HTMLResponse("Not found", status_code=404)

    if FRONTEND_DIST_DIR.exists():
        candidate = FRONTEND_DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index_path = FRONTEND_DIST_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

    return HTMLResponse("Frontend has not been built yet.", status_code=503)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)
