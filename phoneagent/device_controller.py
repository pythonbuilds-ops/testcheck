"""
Device controller abstractions for local ADB and remote companion modes.

The agent and tooling operate against this interface so the transport
can change without rewriting the higher-level orchestration logic.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DeviceCapabilities:
    """Capability manifest advertised by a device controller."""

    ui_tree: bool = True
    screenshots: bool = True
    gestures: bool = True
    text_input: bool = True
    global_actions: bool = True
    notifications: bool = True
    open_url: bool = True
    calls: bool = True
    sms: bool = True
    package_lookup: bool = True
    clipboard: bool = True
    can_force_stop: bool = True
    can_install_apk: bool = True
    can_file_transfer: bool = True
    raw_shell: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ui_tree": self.ui_tree,
            "screenshots": self.screenshots,
            "gestures": self.gestures,
            "text_input": self.text_input,
            "global_actions": self.global_actions,
            "notifications": self.notifications,
            "open_url": self.open_url,
            "calls": self.calls,
            "sms": self.sms,
            "package_lookup": self.package_lookup,
            "clipboard": self.clipboard,
            "can_force_stop": self.can_force_stop,
            "can_install_apk": self.can_install_apk,
            "can_file_transfer": self.can_file_transfer,
            "raw_shell": self.raw_shell,
            "metadata": self.metadata,
        }

    def supported_features(self) -> List[str]:
        return [k for k, v in self.as_dict().items() if isinstance(v, bool) and v]

    def unsupported_features(self) -> List[str]:
        return [k for k, v in self.as_dict().items() if isinstance(v, bool) and not v]


@dataclass
class ObservationBundle:
    """Structured snapshot of the current device state."""

    current_package: str = "unknown"
    current_activity: str = ""
    accessibility_summary: str = ""
    raw_xml: str = ""
    screenshot_available: bool = False
    last_screenshot_analysis: str = ""
    observed_at: float = field(default_factory=time.time)
    source: str = "accessibility"
    node_count: int = 0
    focused_element: str = ""
    screen_signature: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class DeviceController(ABC):
    """Interface implemented by local ADB and companion-app controllers."""

    def __init__(self, mode: str, capabilities: Optional[DeviceCapabilities] = None):
        self.mode = mode
        self._capabilities = capabilities or DeviceCapabilities()

    def get_capabilities(self) -> DeviceCapabilities:
        return self._capabilities

    def supports(self, capability_name: str) -> bool:
        return bool(getattr(self._capabilities, capability_name, False))

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True when the controller can currently talk to a device."""

    @abstractmethod
    def get_device_serial(self) -> Optional[str]:
        """Return a stable device identifier if available."""

    @abstractmethod
    def dump_ui_hierarchy(self) -> Dict[str, Any]:
        """Return UI tree data including XML and any useful metadata."""

    def dump_ui_xml(self) -> str:
        return self.dump_ui_hierarchy().get("xml", "")

    @abstractmethod
    def get_current_activity(self) -> str:
        """Return the current foreground activity, if known."""

    @abstractmethod
    def get_current_package(self) -> str:
        """Return the current foreground package, if known."""

    @abstractmethod
    def tap(self, x: int, y: int) -> str:
        """Tap at screen coordinates."""

    @abstractmethod
    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> str:
        """Long-press at screen coordinates."""

    @abstractmethod
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        """Swipe between coordinates."""

    @abstractmethod
    def swipe_direction(self, direction: str, distance_ratio: float = 0.5) -> str:
        """Swipe in a cardinal direction."""

    @abstractmethod
    def input_text(self, text: str) -> str:
        """Enter text into the focused field."""

    @abstractmethod
    def key_event(self, keycode: str) -> str:
        """Send a global/device key event."""

    def press_back(self) -> str:
        return self.key_event("BACK")

    def press_home(self) -> str:
        return self.key_event("HOME")

    def press_enter(self) -> str:
        return self.key_event("ENTER")

    def press_recents(self) -> str:
        return self.key_event("APP_SWITCH")

    @abstractmethod
    def screenshot_base64(self, max_width: int = 720, quality: int = 60) -> str:
        """Return a screenshot encoded as base64 JPEG."""

    @abstractmethod
    def launch_app(self, package: str) -> str:
        """Launch an application by package or app name."""

    @abstractmethod
    def stop_app(self, package: str) -> str:
        """Close/force-stop an application if supported."""

    @abstractmethod
    def list_packages(self, filter_str: Optional[str] = None) -> List[str]:
        """Return installed package names."""

    @abstractmethod
    def install_app(self, apk_path: str) -> str:
        """Install an application package if supported."""

    @abstractmethod
    def push_file(self, local_path: str, remote_path: str) -> str:
        """Push a file to the device if supported."""

    @abstractmethod
    def pull_file(self, remote_path: str, local_path: str) -> str:
        """Pull a file from the device if supported."""

    @abstractmethod
    def get_device_info(self) -> Dict[str, Any]:
        """Return device metadata."""

    @abstractmethod
    def make_call(self, phone_number: str) -> str:
        """Initiate a phone call if supported."""

    @abstractmethod
    def send_sms(self, phone_number: str, message: str) -> str:
        """Compose/send an SMS if supported."""

    @abstractmethod
    def open_url(self, url: str) -> str:
        """Open a URL on the device."""

    @abstractmethod
    def get_notifications(self) -> str:
        """Return current notification content if supported."""

    @abstractmethod
    def expand_notifications(self) -> str:
        """Open the notification shade if supported."""

    @abstractmethod
    def collapse_notifications(self) -> str:
        """Close the notification shade if supported."""

    @abstractmethod
    def set_clipboard(self, text: str) -> str:
        """Set the device clipboard if supported."""

    @abstractmethod
    def open_settings(self, settings_page: str = "") -> str:
        """Open Android settings or a sub-page."""

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)
