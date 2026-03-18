"""
Companion-app bridge support for remote phone control over WebSockets.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from .device_controller import DeviceCapabilities, DeviceController


class DeviceRPCError(RuntimeError):
    """Raised when the remote companion cannot fulfill a request."""


@dataclass
class CompanionSession:
    """Connected phone companion session."""

    device_id: str
    websocket: WebSocket
    loop: asyncio.AbstractEventLoop
    capabilities: DeviceCapabilities
    device_info: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    connected_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    pending: Dict[str, asyncio.Future] = field(default_factory=dict)

    def is_alive(self, heartbeat_timeout: float) -> bool:
        return (time.time() - self.last_heartbeat) <= heartbeat_timeout


class DeviceSessionManager:
    """Tracks connected phone sessions and forwards RPC calls."""

    def __init__(self, auth_token: str = "", heartbeat_timeout: float = 45.0):
        self.auth_token = auth_token
        self.heartbeat_timeout = heartbeat_timeout
        self._lock = threading.RLock()
        self._sessions: Dict[str, CompanionSession] = {}

    def verify_token(self, token: str) -> bool:
        if not self.auth_token:
            return True
        return token == self.auth_token

    def register_session(
        self,
        device_id: str,
        websocket: WebSocket,
        loop: asyncio.AbstractEventLoop,
        capabilities: Optional[Dict[str, Any]] = None,
        device_info: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CompanionSession:
        caps = capabilities or {}
        session = CompanionSession(
            device_id=device_id,
            websocket=websocket,
            loop=loop,
            capabilities=DeviceCapabilities(**{
                k: v for k, v in caps.items() if k in DeviceCapabilities().__dict__
            }),
            device_info=device_info or {},
            metadata=metadata or {},
        )
        with self._lock:
            previous = self._sessions.get(device_id)
            self._sessions[device_id] = session
        if previous:
            self._cancel_pending(previous, "Replaced by a newer companion session.")
        return session

    def unregister_session(self, device_id: str, websocket: Optional[WebSocket] = None) -> None:
        with self._lock:
            session = self._sessions.get(device_id)
            if not session:
                return
            if websocket is not None and session.websocket is not websocket:
                return
            self._sessions.pop(device_id, None)
        self._cancel_pending(session, "Companion disconnected.")

    def update_heartbeat(
        self,
        device_id: str,
        capabilities: Optional[Dict[str, Any]] = None,
        device_info: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            session = self._sessions.get(device_id)
            if not session:
                return
            session.last_heartbeat = time.time()
            if capabilities:
                session.capabilities = DeviceCapabilities(**{
                    k: v for k, v in capabilities.items() if k in DeviceCapabilities().__dict__
                })
            if device_info:
                session.device_info.update(device_info)
            if metadata:
                session.metadata.update(metadata)

    def handle_response(self, device_id: str, payload: Dict[str, Any]) -> None:
        request_id = payload.get("id")
        if not request_id:
            return
        session = self.get_session(device_id, require_alive=False)
        if not session:
            return
        future = session.pending.get(request_id)
        if future and not future.done():
            future.set_result(payload)

    def get_session(self, device_id: str, require_alive: bool = True) -> Optional[CompanionSession]:
        with self._lock:
            session = self._sessions.get(device_id)
        if not session:
            return None
        if require_alive and not session.is_alive(self.heartbeat_timeout):
            self.unregister_session(device_id, session.websocket)
            return None
        return session

    def get_capabilities(self, device_id: str) -> Optional[DeviceCapabilities]:
        session = self.get_session(device_id)
        return session.capabilities if session else None

    def get_device_info(self, device_id: str) -> Dict[str, Any]:
        session = self.get_session(device_id)
        return dict(session.device_info) if session else {}

    def is_connected(self, device_id: str) -> bool:
        return self.get_session(device_id) is not None

    def call_sync(
        self,
        device_id: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 20.0,
    ) -> Dict[str, Any]:
        session = self.get_session(device_id)
        if not session:
            raise DeviceRPCError(f"Device '{device_id}' is offline.")
        future = asyncio.run_coroutine_threadsafe(
            self._call_async(session, method, params or {}, timeout),
            session.loop,
        )
        try:
            return future.result(timeout + 1.0)
        except Exception as exc:
            raise DeviceRPCError(f"{method} failed: {exc}") from exc

    async def _call_async(
        self,
        session: CompanionSession,
        method: str,
        params: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
        request_id = str(uuid.uuid4())
        response_future = session.loop.create_future()
        session.pending[request_id] = response_future
        try:
            await session.websocket.send_json({
                "type": "rpc_request",
                "id": request_id,
                "method": method,
                "params": params,
            })
            response = await asyncio.wait_for(response_future, timeout=timeout)
        finally:
            session.pending.pop(request_id, None)

        if not response.get("ok", True):
            error = response.get("error") or response.get("result") or "Unknown error"
            raise DeviceRPCError(str(error))
        result = response.get("result", {})
        if isinstance(result, dict):
            capabilities = result.get("capabilities")
            device_info = result.get("device_info")
            metadata = result.get("metadata")
            if capabilities or device_info or metadata:
                self.update_heartbeat(
                    session.device_id,
                    capabilities=capabilities,
                    device_info=device_info,
                    metadata=metadata,
                )
        return result

    def _cancel_pending(self, session: CompanionSession, reason: str) -> None:
        for pending in list(session.pending.values()):
            if not pending.done():
                pending.set_exception(DeviceRPCError(reason))
        session.pending.clear()


class CompanionController(DeviceController):
    """Device controller backed by a connected Android companion app."""

    def __init__(
        self,
        manager: DeviceSessionManager,
        device_id: str,
        request_timeout: float = 20.0,
    ):
        super().__init__(
            mode="companion",
            capabilities=manager.get_capabilities(device_id) or DeviceCapabilities(
                ui_tree=True,
                screenshots=True,
                gestures=True,
                text_input=True,
                global_actions=True,
                notifications=True,
                open_url=True,
                calls=True,
                sms=True,
                package_lookup=True,
                clipboard=True,
                can_force_stop=False,
                can_install_apk=False,
                can_file_transfer=False,
                raw_shell=False,
                metadata={"transport": "companion"},
            ),
        )
        self.manager = manager
        self.device_id = device_id
        self.request_timeout = request_timeout
        self._last_snapshot: Dict[str, Any] = {}

    def get_capabilities(self) -> DeviceCapabilities:
        session_caps = self.manager.get_capabilities(self.device_id)
        if session_caps:
            self._capabilities = session_caps
        return self._capabilities

    def _rpc(self, method: str, **params: Any) -> Dict[str, Any]:
        result = self.manager.call_sync(
            self.device_id,
            method=method,
            params=params,
            timeout=self.request_timeout,
        )
        if method == "dump_ui_tree" and isinstance(result, dict):
            self._last_snapshot = result
        return result

    def _require_support(self, capability_name: str, action: str) -> None:
        if not self.supports(capability_name):
            raise DeviceRPCError(f"The connected phone does not support {action}.")

    def is_connected(self) -> bool:
        return self.manager.is_connected(self.device_id)

    def get_device_serial(self) -> Optional[str]:
        return self.device_id

    def dump_ui_hierarchy(self) -> Dict[str, Any]:
        self._require_support("ui_tree", "UI tree access")
        result = self._rpc("dump_ui_tree")
        return {
            "xml": result.get("xml", ""),
            "package": result.get("package", result.get("current_package", "unknown")),
            "activity": result.get("activity", result.get("current_activity", "")),
            "node_count": result.get("node_count", 0),
            "focused_element": result.get("focused_element", ""),
            "summary": result.get("summary", ""),
            "metadata": result.get("metadata", {}),
        }

    def get_current_activity(self) -> str:
        if self._last_snapshot.get("activity"):
            return str(self._last_snapshot.get("activity", ""))
        return str(self._rpc("health").get("current_activity", ""))

    def get_current_package(self) -> str:
        if self._last_snapshot.get("package") or self._last_snapshot.get("current_package"):
            return str(self._last_snapshot.get("package", self._last_snapshot.get("current_package", "unknown")))
        return str(self._rpc("health").get("current_package", "unknown"))

    def tap(self, x: int, y: int) -> str:
        self._require_support("gestures", "tap gestures")
        self._rpc("tap", x=int(x), y=int(y))
        return ""

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> str:
        self._require_support("gestures", "long-press gestures")
        self._rpc("long_press", x=int(x), y=int(y), duration_ms=int(duration_ms))
        return ""

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        self._require_support("gestures", "swipe gestures")
        self._rpc(
            "swipe",
            x1=int(x1),
            y1=int(y1),
            x2=int(x2),
            y2=int(y2),
            duration_ms=int(duration_ms),
        )
        return ""

    def swipe_direction(self, direction: str, distance_ratio: float = 0.5) -> str:
        self._require_support("gestures", "swipe gestures")
        info = self.get_device_info()
        width = int(info.get("screen_width", 1080))
        height = int(info.get("screen_height", 2400))
        cx, cy = width // 2, height // 2
        dist_x = int(width * float(distance_ratio) / 2)
        dist_y = int(height * float(distance_ratio) / 2)
        swipes = {
            "up": (cx, cy + dist_y, cx, cy - dist_y),
            "down": (cx, cy - dist_y, cx, cy + dist_y),
            "left": (cx + dist_x, cy, cx - dist_x, cy),
            "right": (cx - dist_x, cy, cx + dist_x, cy),
        }
        if direction.lower() not in swipes:
            raise DeviceRPCError(f"Invalid swipe direction: {direction}")
        x1, y1, x2, y2 = swipes[direction.lower()]
        return self.swipe(x1, y1, x2, y2, 400)

    def input_text(self, text: str) -> str:
        self._require_support("text_input", "text input")
        self._rpc("set_text", text=text)
        return ""

    def key_event(self, keycode: str) -> str:
        self._require_support("global_actions", "global actions")
        normalized = keycode.upper()
        action_map = {
            "KEYCODE_BACK": "back",
            "BACK": "back",
            "KEYCODE_HOME": "home",
            "HOME": "home",
            "KEYCODE_APP_SWITCH": "recents",
            "APP_SWITCH": "recents",
        }
        action = action_map.get(normalized)
        if not action:
            raise DeviceRPCError(f"Unsupported companion key event: {keycode}")
        self._rpc("global_action", action=action)
        return ""

    def screenshot_base64(self, max_width: int = 720, quality: int = 60) -> str:
        self._require_support("screenshots", "screenshots")
        result = self._rpc("capture_screenshot", max_width=int(max_width), quality=int(quality))
        image = result.get("image_base64") or result.get("image")
        if not image:
            raise DeviceRPCError("No screenshot data returned by companion.")
        return str(image)

    def launch_app(self, package: str) -> str:
        self._rpc("open_app", package=package)
        return ""

    def stop_app(self, package: str) -> str:
        self._require_support("can_force_stop", "force stop")
        self._rpc("close_app", package=package)
        return ""

    def list_packages(self, filter_str: Optional[str] = None) -> List[str]:
        self._require_support("package_lookup", "package lookup")
        result = self._rpc("list_packages", filter=filter_str or "")
        packages = result.get("packages", [])
        return [str(pkg) for pkg in packages]

    def install_app(self, apk_path: str) -> str:
        self._require_support("can_install_apk", "APK installation")
        self._rpc("install_apk", path=apk_path)
        return ""

    def push_file(self, local_path: str, remote_path: str) -> str:
        self._require_support("can_file_transfer", "file transfer")
        self._rpc("push_file", local_path=local_path, remote_path=remote_path)
        return ""

    def pull_file(self, remote_path: str, local_path: str) -> str:
        self._require_support("can_file_transfer", "file transfer")
        self._rpc("pull_file", remote_path=remote_path, local_path=local_path)
        return ""

    def get_device_info(self) -> Dict[str, Any]:
        if not self.manager.get_device_info(self.device_id):
            result = self._rpc("get_device_info")
            if isinstance(result, dict):
                self.manager.update_heartbeat(self.device_id, device_info=result)
        return self.manager.get_device_info(self.device_id)

    def make_call(self, phone_number: str) -> str:
        self._require_support("calls", "phone calls")
        self._rpc("make_call", phone_number=phone_number)
        return ""

    def send_sms(self, phone_number: str, message: str) -> str:
        self._require_support("sms", "SMS sending")
        self._rpc("send_sms", phone_number=phone_number, message=message)
        return ""

    def open_url(self, url: str) -> str:
        self._require_support("open_url", "URL opening")
        self._rpc("open_url", url=url)
        return ""

    def get_notifications(self) -> str:
        self._require_support("notifications", "notification access")
        result = self._rpc("get_notifications")
        return str(result.get("text", result.get("result", "")))

    def expand_notifications(self) -> str:
        self._require_support("notifications", "notification access")
        self._rpc("global_action", action="notifications")
        return ""

    def collapse_notifications(self) -> str:
        self._require_support("notifications", "notification access")
        self._rpc("global_action", action="collapse_notifications")
        return ""

    def set_clipboard(self, text: str) -> str:
        self._require_support("clipboard", "clipboard access")
        self._rpc("set_clipboard", text=text)
        return ""

    def open_settings(self, settings_page: str = "") -> str:
        self._rpc("open_settings", settings_page=settings_page)
        return ""
