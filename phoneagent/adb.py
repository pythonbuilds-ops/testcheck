"""
ADB Controller — Low-level Android Debug Bridge interface.

Wraps subprocess calls to ADB for all device interactions:
screen taps, swipes, text input, key events, screenshots,
app management, file transfer, and device info.
"""

import subprocess
import base64
import io
import re
import time
from typing import Optional, Tuple, List, Dict, Any

try:
    from PIL import Image
except ImportError:
    Image = None

from .device_controller import DeviceController, DeviceCapabilities


class ADBError(Exception):
    """Raised when an ADB command fails."""
    pass


class ADBController(DeviceController):
    """Low-level ADB command interface for Android device control."""

    def __init__(self, device_serial: Optional[str] = None, adb_path: str = "adb"):
        """
        Initialize ADB controller.

        Args:
            device_serial: Specific device serial (for multi-device setups).
            adb_path: Path to adb executable (default assumes it's on PATH).
        """
        super().__init__(
            mode="local",
            capabilities=DeviceCapabilities(
                ui_tree=True,
                screenshots=Image is not None,
                gestures=True,
                text_input=True,
                global_actions=True,
                notifications=True,
                open_url=True,
                calls=True,
                sms=True,
                package_lookup=True,
                clipboard=True,
                can_force_stop=True,
                can_install_apk=True,
                can_file_transfer=True,
                raw_shell=True,
                metadata={"transport": "adb"},
            ),
        )
        self.device_serial = device_serial
        self.adb_path = adb_path
        self._screen_size_cache: Optional[Tuple[int, int]] = None

    def _build_cmd(self, *args: str) -> List[str]:
        """Build ADB command with optional device serial."""
        cmd = [self.adb_path]
        if self.device_serial:
            cmd.extend(["-s", self.device_serial])
        cmd.extend(args)
        return cmd

    def run_command(self, *args: str, timeout: int = 30) -> str:
        """
        Execute an ADB command and return stdout.

        Args:
            *args: ADB command arguments.
            timeout: Command timeout in seconds.

        Returns:
            Command stdout as string.

        Raises:
            ADBError: If command fails.
        """
        cmd = self._build_cmd(*args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            if result.returncode != 0 and result.stderr.strip():
                raise ADBError(f"ADB command failed: {' '.join(cmd)}\nStderr: {result.stderr.strip()}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise ADBError(f"ADB command timed out after {timeout}s: {' '.join(cmd)}")
        except FileNotFoundError:
            raise ADBError(f"ADB executable not found at '{self.adb_path}'. Ensure ADB is installed and on PATH.")

    def shell(self, command: str, timeout: int = 30) -> str:
        """
        Execute a shell command on the device.

        Args:
            command: Shell command to run.
            timeout: Timeout in seconds.

        Returns:
            Command output.
        """
        return self.run_command("shell", command, timeout=timeout)

    def dump_ui_hierarchy(self) -> Dict[str, Any]:
        xml = self.dump_ui_xml()
        return {
            "xml": xml,
            "package": self.get_current_package(),
            "activity": self.get_current_activity(),
        }

    # ── Connection ──────────────────────────────────────────────

    def is_connected(self) -> bool:
        """Check if a device is connected and responsive."""
        try:
            output = self.run_command("devices")
            lines = [l for l in output.strip().split("\n")[1:] if l.strip()]
            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1].strip() == "device":
                    if self.device_serial is None or parts[0].strip() == self.device_serial:
                        return True
            return False
        except ADBError:
            return False

    def get_device_serial(self) -> Optional[str]:
        """Get the serial of the connected device."""
        try:
            output = self.run_command("devices")
            lines = [l for l in output.strip().split("\n")[1:] if l.strip()]
            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1].strip() == "device":
                    return parts[0].strip()
            return None
        except ADBError:
            return None

    # ── Touch / Input ───────────────────────────────────────────

    def tap(self, x: int, y: int) -> str:
        """Tap at screen coordinates."""
        return self.shell(f"input tap {x} {y}")

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> str:
        """Long press at screen coordinates."""
        return self.shell(f"input swipe {x} {y} {x} {y} {duration_ms}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        """Swipe from (x1,y1) to (x2,y2)."""
        return self.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")

    def swipe_direction(self, direction: str, distance_ratio: float = 0.5) -> str:
        """
        Swipe in a cardinal direction.

        Args:
            direction: 'up', 'down', 'left', 'right'.
            distance_ratio: Fraction of screen dimension to swipe (0-1).
        """
        w, h = self.get_screen_size()
        cx, cy = w // 2, h // 2
        dist_x = int(w * distance_ratio / 2)
        dist_y = int(h * distance_ratio / 2)

        swipes = {
            "up": (cx, cy + dist_y, cx, cy - dist_y),
            "down": (cx, cy - dist_y, cx, cy + dist_y),
            "left": (cx + dist_x, cy, cx - dist_x, cy),
            "right": (cx - dist_x, cy, cx + dist_x, cy),
        }
        if direction.lower() not in swipes:
            raise ADBError(f"Invalid swipe direction: {direction}. Use up/down/left/right.")

        x1, y1, x2, y2 = swipes[direction.lower()]
        return self.swipe(x1, y1, x2, y2, 400)

    def input_text(self, text: str) -> str:
        """
        Type text via ADB. Handles special characters by escaping.

        Args:
            text: Text to type.
        """
        # ADB input text has issues with special chars, escape them
        escaped = text.replace("\\", "\\\\")
        escaped = escaped.replace(" ", "%s")
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace("&", "\\&")
        escaped = escaped.replace("<", "\\<")
        escaped = escaped.replace(">", "\\>")
        escaped = escaped.replace("|", "\\|")
        escaped = escaped.replace(";", "\\;")
        escaped = escaped.replace("(", "\\(")
        escaped = escaped.replace(")", "\\)")
        return self.shell(f'input text "{escaped}"')

    def key_event(self, keycode: str) -> str:
        """
        Send a key event.

        Args:
            keycode: Android keycode name or number.
                     Common: KEYCODE_BACK, KEYCODE_HOME, KEYCODE_ENTER,
                     KEYCODE_VOLUME_UP, KEYCODE_VOLUME_DOWN, KEYCODE_POWER,
                     KEYCODE_APP_SWITCH (recents), KEYCODE_MENU
        """
        if not keycode.startswith("KEYCODE_"):
            keycode = f"KEYCODE_{keycode.upper()}"
        return self.shell(f"input keyevent {keycode}")

    def press_back(self) -> str:
        """Press the back button."""
        return self.key_event("BACK")

    def press_home(self) -> str:
        """Press the home button."""
        return self.key_event("HOME")

    def press_enter(self) -> str:
        """Press enter/return."""
        return self.key_event("ENTER")

    def press_recents(self) -> str:
        """Open recent apps."""
        return self.key_event("APP_SWITCH")

    # ── Screen ──────────────────────────────────────────────────

    def get_screen_size(self) -> Tuple[int, int]:
        """Get device screen resolution as (width, height)."""
        if self._screen_size_cache:
            return self._screen_size_cache

        output = self.shell("wm size")
        match = re.search(r"(\d+)x(\d+)", output)
        if not match:
            raise ADBError(f"Could not parse screen size from: {output}")
        self._screen_size_cache = (int(match.group(1)), int(match.group(2)))
        return self._screen_size_cache

    def screenshot(self, max_width: int = 720) -> "Image.Image":
        """
        Capture a screenshot and return as PIL Image.

        Args:
            max_width: Maximum width to resize to (saves tokens on vision).

        Returns:
            PIL Image object.
        """
        if Image is None:
            raise ADBError("Pillow is not installed. Run: pip install Pillow")

        # Capture raw PNG bytes via screencap
        cmd = self._build_cmd("exec-out", "screencap", "-p")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            if result.returncode != 0:
                raise ADBError(f"Screenshot failed: {result.stderr.decode(errors='replace')}")

            img = Image.open(io.BytesIO(result.stdout))

            # Resize if too large
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            return img
        except subprocess.TimeoutExpired:
            raise ADBError("Screenshot timed out")

    def screenshot_base64(self, max_width: int = 720, quality: int = 60) -> str:
        """
        Capture screenshot and return as base64-encoded JPEG.

        Args:
            max_width: Maximum width for resizing.
            quality: JPEG quality (1-100).

        Returns:
            Base64 encoded JPEG string.
        """
        img = self.screenshot(max_width=max_width)
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    # ── App Management ──────────────────────────────────────────

    def launch_app(self, package: str) -> str:
        """
        Launch an app by package name using monkey.

        Args:
            package: Android package name (e.g., 'com.whatsapp').
        """
        return self.shell(
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
        )

    def stop_app(self, package: str) -> str:
        """Force stop an app."""
        return self.shell(f"am force-stop {package}")

    def get_current_activity(self) -> str:
        """Get the currently focused activity/package."""
        # Try dumpsys
        output = self.shell("dumpsys activity activities | grep mResumedActivity")
        if output:
            return output.strip()
        # Fallback
        output = self.shell("dumpsys window | grep mCurrentFocus")
        return output.strip()

    def get_current_package(self) -> str:
        """Get the package name of the currently foreground app."""
        output = self.shell(
            "dumpsys activity activities | grep mResumedActivity"
        )
        match = re.search(r"(\S+)/(\S+)", output)
        if match:
            return match.group(1)
        return "unknown"

    def list_packages(self, filter_str: Optional[str] = None) -> List[str]:
        """
        List installed packages.

        Args:
            filter_str: Optional filter string to match package names.
        """
        cmd = "pm list packages"
        if filter_str:
            cmd += f" | grep -i {filter_str}"
        output = self.shell(cmd)
        packages = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line[8:])
            elif line:
                packages.append(line)
        return packages

    def install_app(self, apk_path: str) -> str:
        """Install an APK from the host machine."""
        return self.run_command("install", "-r", apk_path, timeout=120)

    def uninstall_app(self, package: str) -> str:
        """Uninstall an app."""
        return self.run_command("uninstall", package, timeout=60)

    # ── File Transfer ───────────────────────────────────────────

    def push_file(self, local_path: str, remote_path: str) -> str:
        """Push a file from host to device."""
        return self.run_command("push", local_path, remote_path, timeout=120)

    def pull_file(self, remote_path: str, local_path: str) -> str:
        """Pull a file from device to host."""
        return self.run_command("pull", remote_path, local_path, timeout=120)

    # ── Device Info ─────────────────────────────────────────────

    def get_device_info(self) -> Dict[str, str]:
        """Get comprehensive device information."""
        info = {}
        props = {
            "model": "ro.product.model",
            "brand": "ro.product.brand",
            "android_version": "ro.build.version.release",
            "sdk_version": "ro.build.version.sdk",
            "device_name": "ro.product.device",
        }
        for key, prop in props.items():
            try:
                info[key] = self.shell(f"getprop {prop}")
            except ADBError:
                info[key] = "unknown"

        # Battery
        try:
            battery_output = self.shell("dumpsys battery")
            level_match = re.search(r"level:\s*(\d+)", battery_output)
            status_match = re.search(r"status:\s*(\d+)", battery_output)
            if level_match:
                info["battery_level"] = f"{level_match.group(1)}%"
            if status_match:
                status_map = {"1": "unknown", "2": "charging", "3": "discharging",
                              "4": "not charging", "5": "full"}
                info["battery_status"] = status_map.get(status_match.group(1), "unknown")
        except ADBError:
            pass

        # Screen state
        try:
            screen_output = self.shell("dumpsys power | grep mScreenOn")
            info["screen_on"] = "true" in screen_output.lower()
        except ADBError:
            pass

        return info

    def get_battery_level(self) -> int:
        """Get battery percentage."""
        output = self.shell("dumpsys battery")
        match = re.search(r"level:\s*(\d+)", output)
        return int(match.group(1)) if match else -1

    def wake_screen(self) -> str:
        """Wake the screen if it's off."""
        return self.key_event("WAKEUP")

    def unlock_screen(self) -> str:
        """Attempt to unlock screen (swipe up + dismiss keyguard)."""
        self.key_event("WAKEUP")
        time.sleep(0.5)
        w, h = self.get_screen_size()
        self.swipe(w // 2, int(h * 0.8), w // 2, int(h * 0.2), 300)
        time.sleep(0.3)
        return self.shell("wm dismiss-keyguard")

    # ── Telephony / SMS ─────────────────────────────────────────

    def make_call(self, phone_number: str) -> str:
        """Initiate a phone call."""
        return self.shell(
            f"am start -a android.intent.action.CALL -d tel:{phone_number}"
        )

    def send_sms(self, phone_number: str, message: str) -> str:
        """
        Open SMS compose with pre-filled number and message.
        Note: This opens the SMS app, actual sending depends on the app.
        """
        escaped_msg = message.replace(" ", "%20")
        return self.shell(
            f'am start -a android.intent.action.SENDTO -d "sms:{phone_number}" '
            f'--es sms_body "{message}" --ez exit_on_sent true'
        )

    def open_url(self, url: str) -> str:
        """Open a URL in the default browser."""
        return self.shell(
            f'am start -a android.intent.action.VIEW -d "{url}"'
        )

    # ── Notifications ───────────────────────────────────────────

    def get_notifications(self) -> str:
        """Dump current notifications (requires appropriate permissions)."""
        return self.shell("dumpsys notification --noredact")

    def expand_notifications(self) -> str:
        """Pull down the notification shade."""
        return self.shell("cmd statusbar expand-notifications")

    def collapse_notifications(self) -> str:
        """Close the notification shade."""
        return self.shell("cmd statusbar collapse")

    # ── Clipboard ───────────────────────────────────────────────

    def set_clipboard(self, text: str) -> str:
        """Set device clipboard text (requires API 29+)."""
        return self.shell(f'am broadcast -a clipper.set -e text "{text}"')

    # ── Settings ────────────────────────────────────────────────

    def open_settings(self, settings_page: str = "") -> str:
        """
        Open device settings.

        Args:
            settings_page: Specific settings constant, e.g.:
                'android.settings.WIFI_SETTINGS'
                'android.settings.BLUETOOTH_SETTINGS'
                'android.settings.DISPLAY_SETTINGS'
                'android.settings.SOUND_SETTINGS'
                'android.settings.APPLICATION_SETTINGS'
                '' for main settings page.
        """
        if settings_page:
            return self.shell(
                f"am start -a {settings_page}"
            )
        return self.shell(
            "am start -a android.settings.SETTINGS"
        )

    # ── UI Hierarchy (raw) ──────────────────────────────────────

    def dump_ui_xml(self) -> str:
        """
        Dump UI hierarchy XML using uiautomator.

        Returns:
            Raw XML string of the current UI tree.
        """
        self.shell("uiautomator dump /sdcard/ui_dump.xml", timeout=15)
        time.sleep(0.5)
        xml_content = self.shell("cat /sdcard/ui_dump.xml", timeout=10)
        self.shell("rm /sdcard/ui_dump.xml")
        return xml_content

    def wait(self, seconds: float) -> None:
        """Wait for specified seconds (host-side delay)."""
        time.sleep(seconds)
