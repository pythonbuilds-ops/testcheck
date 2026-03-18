"""
Phone Tools — All high-level tools available to the agent.

Each tool wraps ADB/accessibility/vision operations and is
registered in the ToolRegistry for LLM-driven execution.
"""

import time
from typing import Dict, Any, Optional

from .tools import Tool, ToolParameter, ToolRegistry
from .accessibility import AccessibilityParser
from .device_controller import DeviceController
from .memory import MemorySystem


def register_all_tools(
    registry: ToolRegistry,
    controller: DeviceController,
    accessibility: AccessibilityParser,
    memory: MemorySystem,
    vision_analyzer=None,
):
    """
    Register all phone tools into the given registry.

    Args:
        registry: ToolRegistry to populate.
        controller: Device controller instance.
        accessibility: Accessibility parser instance.
        memory: Memory system instance.
        vision_analyzer: Optional VisionAnalyzer instance.
    """
    adb = controller
    capabilities = controller.get_capabilities()

    def has(capability_name: str) -> bool:
        return bool(getattr(capabilities, capability_name, False))

    # ── Navigation Tools ────────────────────────────────────────

    def tap_element(text: str = "", content_desc: str = "", resource_id: str = "") -> Dict[str, Any]:
        """Tap a UI element by matching its text, description, or resource ID."""
        elements = accessibility.dump_and_parse()
        matches = accessibility.find_elements(
            elements,
            text=text or None,
            content_desc=content_desc or None,
            resource_id=resource_id or None,
            clickable=True,
        )
        if not matches:
            # Broaden search: try without clickable filter
            matches = accessibility.find_elements(
                elements,
                text=text or None,
                content_desc=content_desc or None,
                resource_id=resource_id or None,
            )
        if not matches:
            return {"success": False, "result": f"Element not found. Text='{text}', desc='{content_desc}', id='{resource_id}'"}

        # Take the first match
        el = matches[0]
        cx, cy = el.center
        adb.tap(cx, cy)
        time.sleep(0.8)
        return {"success": True, "result": f"Tapped '{el.display_text}' at ({cx}, {cy})"}

    if has("ui_tree") and has("gestures"):
        registry.register(Tool(
            name="tap_element",
            description="Tap a UI element by its text, content description, or resource ID. At least one identifier must be provided.",
            parameters=[
                ToolParameter("text", "Visible text of the element to tap", required=False, default=""),
                ToolParameter("content_desc", "Content description / accessibility label", required=False, default=""),
                ToolParameter("resource_id", "Resource ID (e.g., 'com.app:id/button')", required=False, default=""),
            ],
            execute_fn=tap_element,
            category="navigation",
        ))

    def tap_coordinates(x: int, y: int) -> Dict[str, Any]:
        """Tap at specific screen coordinates."""
        x, y = int(x), int(y)
        adb.tap(x, y)
        time.sleep(0.5)
        return {"success": True, "result": f"Tapped at ({x}, {y})"}

    if has("gestures"):
        registry.register(Tool(
            name="tap_coordinates",
            description="Tap at specific x, y screen coordinates.",
            parameters=[
                ToolParameter("x", "X coordinate", type="integer"),
                ToolParameter("y", "Y coordinate", type="integer"),
            ],
            execute_fn=tap_coordinates,
            category="navigation",
        ))

    def type_text(text: str) -> Dict[str, Any]:
        """Type text into the currently focused input field."""
        adb.input_text(text)
        time.sleep(0.3)
        return {"success": True, "result": f"Typed: '{text}'"}

    if has("text_input"):
        registry.register(Tool(
            name="type_text",
            description="Type text into the currently focused input field. Make sure an input field is focused first by tapping on it.",
            parameters=[
                ToolParameter("text", "Text to type"),
            ],
            execute_fn=type_text,
            category="navigation",
        ))

    def swipe(direction: str, distance: float = 0.5) -> Dict[str, Any]:
        """Swipe in a direction on the screen."""
        distance = float(distance)
        adb.swipe_direction(direction, distance_ratio=distance)
        time.sleep(0.5)
        return {"success": True, "result": f"Swiped {direction} (distance={distance})"}

    if has("gestures"):
        registry.register(Tool(
            name="swipe",
            description="Swipe on the screen in a direction. Use for scrolling, dismissing, navigating.",
            parameters=[
                ToolParameter("direction", "Swipe direction", enum=["up", "down", "left", "right"]),
                ToolParameter("distance", "Swipe distance as fraction of screen (0.0-1.0)", type="number", required=False, default=0.5),
            ],
            execute_fn=swipe,
            category="navigation",
        ))

    def scroll_to_find(text: str, max_scrolls: int = 10, direction: str = "up") -> Dict[str, Any]:
        """Scroll until an element with the given text is visible."""
        max_scrolls = int(max_scrolls)
        for i in range(max_scrolls):
            elements = accessibility.dump_and_parse()
            matches = accessibility.find_elements(elements, text=text)
            if matches:
                el = matches[0]
                return {"success": True, "result": f"Found '{text}' after {i} scrolls at ({el.center[0]}, {el.center[1]})"}
            adb.swipe_direction(direction, 0.4)
            time.sleep(1)

        return {"success": False, "result": f"Could not find '{text}' after {max_scrolls} scrolls"}

    if has("ui_tree") and has("gestures"):
        registry.register(Tool(
            name="scroll_to_find",
            description="Scroll the screen until an element with the given text becomes visible.",
            parameters=[
                ToolParameter("text", "Text to search for while scrolling"),
                ToolParameter("max_scrolls", "Maximum number of scrolls to attempt", type="integer", required=False, default=10),
                ToolParameter("direction", "Scroll direction (swipe up = scroll down)", enum=["up", "down"], required=False, default="up"),
            ],
            execute_fn=scroll_to_find,
            category="navigation",
        ))

    def press_key(key: str) -> Dict[str, Any]:
        """Press a hardware/software key."""
        key_map = {
            "back": "BACK",
            "home": "HOME",
            "enter": "ENTER",
            "recents": "APP_SWITCH",
            "menu": "MENU",
            "volume_up": "VOLUME_UP",
            "volume_down": "VOLUME_DOWN",
            "power": "POWER",
            "tab": "TAB",
            "delete": "DEL",
            "search": "SEARCH",
        }
        keycode = key_map.get(key.lower(), key.upper())
        adb.key_event(keycode)
        time.sleep(0.3)
        return {"success": True, "result": f"Pressed key: {keycode}"}

    available_keys = (
        ["back", "home", "recents"]
        if controller.mode == "companion"
        else ["back", "home", "enter", "recents", "menu", "volume_up", "volume_down", "power", "tab", "delete", "search"]
    )
    if has("global_actions"):
        registry.register(Tool(
            name="press_key",
            description=f"Press a device key. Available keys: {', '.join(available_keys)}.",
            parameters=[
                ToolParameter("key", "Key to press", enum=available_keys),
            ],
            execute_fn=press_key,
            category="navigation",
        ))

    def long_press_element(text: str = "", x: int = 0, y: int = 0, duration: int = 1000) -> Dict[str, Any]:
        """Long press on an element or coordinates."""
        duration = int(duration)
        if text:
            elements = accessibility.dump_and_parse()
            matches = accessibility.find_elements(elements, text=text)
            if not matches:
                return {"success": False, "result": f"Element with text '{text}' not found"}
            cx, cy = matches[0].center
        else:
            cx, cy = int(x), int(y)

        adb.long_press(cx, cy, duration)
        time.sleep(0.5)
        return {"success": True, "result": f"Long pressed at ({cx}, {cy}) for {duration}ms"}

    if has("gestures"):
        registry.register(Tool(
            name="long_press",
            description="Long press on an element by text or at specific coordinates.",
            parameters=[
                ToolParameter("text", "Text of element to long press", required=False, default=""),
                ToolParameter("x", "X coordinate (if no text)", type="integer", required=False, default=0),
                ToolParameter("y", "Y coordinate (if no text)", type="integer", required=False, default=0),
                ToolParameter("duration", "Press duration in milliseconds", type="integer", required=False, default=1000),
            ],
            execute_fn=long_press_element,
            category="navigation",
        ))

    # ── App Management ──────────────────────────────────────────

    def open_app(name: str) -> Dict[str, Any]:
        """Open an app by name or package."""
        # 1. Direct package name (e.g., com.whatsapp)
        if "." in name and " " not in name:
            adb.launch_app(name)
            time.sleep(2)
            memory.store(f"app_pkg:{name.split('.')[-1]}", name, "app_knowledge", importance=8, source="discovery")
            return {"success": True, "result": f"Launched {name}"}

        search_key = name.lower().strip()

        # 2. Exact memory lookup (most reliable, no fuzzy matching)
        pkg = memory.get_exact(f"app_pkg:{search_key}")
        if pkg:
            adb.launch_app(pkg)
            time.sleep(2)
            # Verify it actually launched
            current = adb.get_current_package()
            if current != "unknown" and pkg in current:
                return {"success": True, "result": f"Launched {name} ({pkg}) — verified on screen"}
            return {"success": True, "result": f"Launched {name} ({pkg})"}

        # 3. Scanned app registry (populated at startup)
        registry_pkg = memory.get_exact(f"app_registry:{search_key}")
        if registry_pkg:
            adb.launch_app(registry_pkg)
            time.sleep(2)
            # Also save as app_pkg for fast lookup next time
            memory.store(f"app_pkg:{search_key}", registry_pkg, "app_knowledge", importance=8, source="discovery")
            return {"success": True, "result": f"Launched {name} ({registry_pkg}) from app registry"}

        # 4. Common apps fallback table
        common_apps = {
            "whatsapp": "com.whatsapp",
            "instagram": "com.instagram.android",
            "youtube": "com.google.android.youtube",
            "chrome": "com.android.chrome",
            "camera": "com.android.camera",
            "phone": "com.android.dialer",
            "dialer": "com.android.dialer",
            "messages": "com.google.android.apps.messaging",
            "gmail": "com.google.android.gm",
            "maps": "com.google.android.apps.maps",
            "photos": "com.google.android.apps.photos",
            "settings": "com.android.settings",
            "clock": "com.google.android.deskclock",
            "alarm": "com.google.android.deskclock",
            "calculator": "com.google.android.calculator",
            "calendar": "com.google.android.calendar",
            "contacts": "com.android.contacts",
            "files": "com.google.android.apps.nbu.files",
            "play store": "com.android.vending",
            "playstore": "com.android.vending",
            "spotify": "com.spotify.music",
            "twitter": "com.twitter.android",
            "x": "com.twitter.android",
            "telegram": "org.telegram.messenger",
            "facebook": "com.facebook.katana",
            "netflix": "com.netflix.mediaclient",
        }

        pkg = common_apps.get(search_key)
        if pkg:
            adb.launch_app(pkg)
            time.sleep(2)
            memory.store(f"app_pkg:{search_key}", pkg, "app_knowledge", importance=8, source="discovery")
            return {"success": True, "result": f"Launched {name} ({pkg})"}

        # 5. Fuzzy search installed packages
        try:
            packages = adb.list_packages()
            search_name = search_key.replace(" ", "")
            for p in packages:
                if search_name in p.lower():
                    adb.launch_app(p)
                    time.sleep(2)
                    memory.store(f"app_pkg:{search_key}", p, "app_knowledge", importance=8, source="discovery")
                    return {"success": True, "result": f"Launched {name} ({p}) via package search"}
        except Exception:
            pass

        return {
            "success": False,
            "result": (
                f"App '{name}' not found. Try the exact package name, a more precise app name, "
                "or ask the user to open the app manually first."
            ),
        }

    registry.register(Tool(
        name="open_app",
        description="Launch an app by its name (e.g., 'WhatsApp', 'Settings') or package name (e.g., 'com.whatsapp').",
        parameters=[
            ToolParameter("name", "App name or package name"),
        ],
        execute_fn=open_app,
        category="apps",
    ))

    def close_app(name: str) -> Dict[str, Any]:
        """Force stop an app."""
        if "." in name:
            adb.stop_app(name)
        else:
            # Find package
            mem_results = memory.recall(f"app_package {name}", top_k=1, category="app_knowledge")
            if mem_results:
                adb.stop_app(mem_results[0]["value"])
            else:
                packages = adb.list_packages(name.lower())
                if packages:
                    adb.stop_app(packages[0])
                else:
                    return {"success": False, "result": f"Could not find package for '{name}'"}
        time.sleep(0.5)
        return {"success": True, "result": f"Stopped {name}"}

    if has("can_force_stop"):
        registry.register(Tool(
            name="close_app",
            description="Force stop / close an app by name or package.",
            parameters=[
                ToolParameter("name", "App name or package name to close"),
            ],
            execute_fn=close_app,
            category="apps",
        ))

    # ── Screen Info ─────────────────────────────────────────────

    def take_screenshot() -> Dict[str, Any]:
        """Capture and analyze screenshot with vision model."""
        if vision_analyzer:
            result = vision_analyzer.capture_and_analyze()
            # Map 'description' to 'result' so the agent history captures the analysis
            if result.get("success") and result.get("description"):
                result["result"] = f"[Vision Analysis]\n{result['description']}"
            elif not result.get("success"):
                result["result"] = result.get("description", "Vision analysis failed")
            else:
                result["result"] = "(Screenshot taken but no analysis returned)"
            return result
        return {"success": False, "result": "Vision analyzer not available"}

    if has("screenshots"):
        registry.register(Tool(
            name="take_screenshot",
            description="Capture the current screen and analyze it visually using the vision model. Use when accessibility tree is not sufficient.",
            parameters=[],
            execute_fn=take_screenshot,
            category="screen",
        ))

    def get_screen_info() -> Dict[str, Any]:
        """Get current screen info via accessibility tree."""
        elements = accessibility.dump_and_parse()
        summary = accessibility.build_screen_summary(elements)
        pkg = adb.get_current_package()

        # Auto-discover current app
        activity = adb.get_current_activity()
        if pkg != "unknown":
            memory.auto_discover(f"last_seen_app", pkg, "app_knowledge")

        return {
            "success": True,
            "result": f"Current app: {pkg}\n{summary}",
            "package": pkg,
            "element_count": len(elements),
        }

    if has("ui_tree"):
        registry.register(Tool(
            name="get_screen_info",
            description="Get a structured summary of the current screen using the accessibility tree. Faster and cheaper than screenshots. Use this first before take_screenshot.",
            parameters=[],
            execute_fn=get_screen_info,
            category="screen",
        ))

    def read_screen_text() -> Dict[str, Any]:
        """Read all text from the current screen."""
        elements = accessibility.dump_and_parse()
        text = accessibility.get_full_screen_text(elements)
        if not text.strip():
            # Fallback to vision
            if vision_analyzer:
                return vision_analyzer.read_screen_text()
            return {"success": True, "result": "(No text found on screen)"}
        return {"success": True, "result": text}

    if has("ui_tree") or has("screenshots"):
        registry.register(Tool(
            name="read_screen_text",
            description="Extract all visible text from the current screen. Uses accessibility tree first, falls back to vision.",
            parameters=[],
            execute_fn=read_screen_text,
            category="screen",
        ))

    # ── Communication ───────────────────────────────────────────

    def open_url(url: str) -> Dict[str, Any]:
        """Open a URL in the default browser."""
        adb.open_url(url)
        time.sleep(2)
        return {"success": True, "result": f"Opened URL: {url}"}

    if has("open_url"):
        registry.register(Tool(
            name="open_url",
            description="Open a URL in the device's default browser.",
            parameters=[
                ToolParameter("url", "The URL to open"),
            ],
            execute_fn=open_url,
            category="communication",
        ))

    def make_call(phone_number: str) -> Dict[str, Any]:
        """Initiate a phone call."""
        adb.make_call(phone_number)
        time.sleep(1)
        return {"success": True, "result": f"Calling {phone_number}"}

    if has("calls"):
        registry.register(Tool(
            name="make_call",
            description="Initiate a phone call to a number.",
            parameters=[
                ToolParameter("phone_number", "Phone number to call"),
            ],
            execute_fn=make_call,
            category="communication",
        ))

    def send_sms(phone_number: str, message: str) -> Dict[str, Any]:
        """Send an SMS message."""
        adb.send_sms(phone_number, message)
        time.sleep(1)
        return {"success": True, "result": f"SMS opened to {phone_number}: '{message}'"}

    if has("sms"):
        registry.register(Tool(
            name="send_sms",
            description="Open SMS compose with a pre-filled number and message.",
            parameters=[
                ToolParameter("phone_number", "Recipient phone number"),
                ToolParameter("message", "Message text to send"),
            ],
            execute_fn=send_sms,
            category="communication",
        ))

    # ── Notifications ───────────────────────────────────────────

    def read_notifications() -> Dict[str, Any]:
        """Read current notifications."""
        try:
            output = adb.get_notifications()
            # Parse out notification text
            lines = output.split("\n")
            notifications = []
            for line in lines:
                if "android.title=" in line or "android.text=" in line:
                    notifications.append(line.strip())

            if not notifications:
                # Try expanding and reading via accessibility
                adb.expand_notifications()
                time.sleep(1)
                elements = accessibility.dump_and_parse()
                text = accessibility.get_full_screen_text(elements)
                adb.collapse_notifications()
                time.sleep(0.5)
                return {"success": True, "result": f"Notification shade:\n{text}"}

            return {"success": True, "result": "\n".join(notifications[:20])}
        except Exception as e:
            return {"success": False, "result": f"Could not read notifications: {str(e)}"}

    if has("notifications"):
        registry.register(Tool(
            name="read_notifications",
            description="Read current device notifications.",
            parameters=[],
            execute_fn=read_notifications,
            category="device",
        ))

    # ── Settings ────────────────────────────────────────────────

    def open_settings(page: str = "") -> Dict[str, Any]:
        """Open device settings, optionally a specific page."""
        settings_map = {
            "": "",
            "wifi": "android.settings.WIFI_SETTINGS",
            "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
            "display": "android.settings.DISPLAY_SETTINGS",
            "sound": "android.settings.SOUND_SETTINGS",
            "apps": "android.settings.APPLICATION_SETTINGS",
            "battery": "android.intent.action.POWER_USAGE_SUMMARY",
            "storage": "android.settings.INTERNAL_STORAGE_SETTINGS",
            "location": "android.settings.LOCATION_SOURCE_SETTINGS",
            "security": "android.settings.SECURITY_SETTINGS",
            "accounts": "android.settings.SYNC_SETTINGS",
            "accessibility": "android.settings.ACCESSIBILITY_SETTINGS",
            "developer": "android.settings.APPLICATION_DEVELOPMENT_SETTINGS",
            "about": "android.settings.DEVICE_INFO_SETTINGS",
        }
        setting = settings_map.get(page.lower(), page)
        adb.open_settings(setting)
        time.sleep(1)
        return {"success": True, "result": f"Opened settings{': ' + page if page else ''}"}

    registry.register(Tool(
        name="open_settings",
        description="Open device settings. Optionally specify a page: wifi, bluetooth, display, sound, apps, battery, storage, location, security, accounts, accessibility, developer, about.",
        parameters=[
            ToolParameter("page", "Settings page to open (leave empty for main settings)", required=False, default=""),
        ],
        execute_fn=open_settings,
        category="device",
    ))

    # ── Device ──────────────────────────────────────────────────

    def get_device_status() -> Dict[str, Any]:
        """Get device status information."""
        info = adb.get_device_info()
        parts = [f"{k}: {v}" for k, v in info.items()]
        return {"success": True, "result": "\n".join(parts)}

    registry.register(Tool(
        name="get_device_status",
        description="Get device information: model, battery level, Android version, etc.",
        parameters=[],
        execute_fn=get_device_status,
        category="device",
    ))

    def install_apk(path: str) -> Dict[str, Any]:
        """Install an APK file from the host machine."""
        result = adb.install_app(path)
        return {"success": True, "result": f"Installed: {result}"}

    if has("can_install_apk"):
        registry.register(Tool(
            name="install_apk",
            description="Install an APK file from the computer to the device.",
            parameters=[
                ToolParameter("path", "Path to APK file on host machine"),
            ],
            execute_fn=install_apk,
            category="device",
        ))

    def file_transfer(action: str, local_path: str, remote_path: str) -> Dict[str, Any]:
        """Transfer files between host and device."""
        if action.lower() == "push":
            result = adb.push_file(local_path, remote_path)
        elif action.lower() == "pull":
            result = adb.pull_file(remote_path, local_path)
        else:
            return {"success": False, "result": f"Invalid action '{action}'. Use 'push' or 'pull'."}
        return {"success": True, "result": result}

    if has("can_file_transfer"):
        registry.register(Tool(
            name="file_transfer",
            description="Transfer files between the computer and device. 'push' sends to device, 'pull' gets from device.",
            parameters=[
                ToolParameter("action", "Transfer direction", enum=["push", "pull"]),
                ToolParameter("local_path", "File path on host computer"),
                ToolParameter("remote_path", "File path on device (e.g., /sdcard/file.txt)"),
            ],
            execute_fn=file_transfer,
            category="device",
        ))

    # ── Clipboard ───────────────────────────────────────────────

    def set_clipboard(text: str) -> Dict[str, Any]:
        """Set device clipboard text."""
        adb.set_clipboard(text)
        return {"success": True, "result": f"Clipboard set to: '{text[:50]}...'"}

    if has("clipboard"):
        registry.register(Tool(
            name="set_clipboard",
            description="Set the device clipboard to the given text.",
            parameters=[
                ToolParameter("text", "Text to copy to clipboard"),
            ],
            execute_fn=set_clipboard,
            category="device",
        ))

    # ── Utility ─────────────────────────────────────────────────

    def wait_seconds(seconds: float = 2) -> Dict[str, Any]:
        """Wait for a specified duration."""
        seconds = float(seconds)
        time.sleep(seconds)
        return {"success": True, "result": f"Waited {seconds} seconds"}

    registry.register(Tool(
        name="wait",
        description="Wait for a specified number of seconds. Useful for waiting for animations, loading, etc.",
        parameters=[
            ToolParameter("seconds", "Seconds to wait", type="number", required=False, default=2),
        ],
        execute_fn=wait_seconds,
        category="utility",
    ))

    # ── Memory Tools ────────────────────────────────────────────

    def store_memory(key: str, value: str, category: str = "general") -> Dict[str, Any]:
        """Store a fact in long-term memory."""
        memory.store(key, value, category=category, source="user")
        return {"success": True, "result": f"Stored: {key} = {value} [{category}]"}

    registry.register(Tool(
        name="store_memory",
        description="Store a fact or piece of information in long-term memory for future recall. Use for user preferences, learned info, etc.",
        parameters=[
            ToolParameter("key", "Short descriptive key (e.g., 'user_name', 'favorite_app')"),
            ToolParameter("value", "The value/fact to remember"),
            ToolParameter("category", "Category: user_preference, app_knowledge, device_info, learned_procedure, contact, general",
                         required=False, default="general"),
        ],
        execute_fn=store_memory,
        category="memory",
    ))

    def recall_memory(query: str) -> Dict[str, Any]:
        """Search long-term memory."""
        results = memory.recall(query, top_k=5)
        if not results:
            return {"success": True, "result": "No matching memories found."}
        parts = [f"- {r['key']}: {r['value']} [{r['category']}]" for r in results]
        return {"success": True, "result": "Memories:\n" + "\n".join(parts)}

    registry.register(Tool(
        name="recall_memory",
        description="Search long-term memory for stored facts and information.",
        parameters=[
            ToolParameter("query", "Search query to find relevant memories"),
        ],
        execute_fn=recall_memory,
        category="memory",
    ))

    def forget_memory(key: str) -> Dict[str, Any]:
        """Remove a fact from long-term memory by its exact key."""
        success = memory.forget(key)
        if success:
            return {"success": True, "result": f"Forgotten: '{key}' removed from memory"}
        # Try fuzzy match to find the right key
        results = memory.recall(key, top_k=5)
        if results:
            keys_found = ", ".join(r["key"] for r in results)
            return {"success": False, "result": f"Key '{key}' not found exactly. Similar keys: {keys_found}. Try one of these."}
        return {"success": False, "result": f"Nothing found matching '{key}' in memory"}

    registry.register(Tool(
        name="forget_memory",
        description="Remove/delete a fact from long-term memory. Use when the user says to forget something or when stored info is wrong.",
        parameters=[
            ToolParameter("key", "The exact key of the memory to forget (use recall_memory first to find the key)"),
        ],
        execute_fn=forget_memory,
        category="memory",
    ))

    def update_memory(key: str, value: str, category: str = "") -> Dict[str, Any]:
        """Update an existing memory or create a new one."""
        # If category not specified, try to keep existing category
        if not category:
            existing = memory.recall(key, top_k=1)
            if existing and existing[0]["key"] == key:
                category = existing[0].get("category", "general")
            else:
                category = "general"
        memory.store(key, value, category=category, importance=6, source="user")
        return {"success": True, "result": f"Updated: {key} = {value} [{category}]"}

    registry.register(Tool(
        name="update_memory",
        description="Update an existing memory entry or create a new one. Use when user says to change/correct stored information.",
        parameters=[
            ToolParameter("key", "Key of the memory to update"),
            ToolParameter("value", "New value to store"),
            ToolParameter("category", "Category (leave empty to keep existing)", required=False, default=""),
        ],
        execute_fn=update_memory,
        category="memory",
    ))

    def list_memories(category: str = "", limit: int = 20) -> Dict[str, Any]:
        """List all stored memories, optionally filtered by category."""
        limit = int(limit)
        if category:
            results = memory.recall_by_category(category, limit=limit)
        else:
            results = memory.get_all_memories(limit=limit)
        if not results:
            return {"success": True, "result": "No memories stored yet."}
        parts = [f"- [{r['category']}] {r['key']}: {r['value']}" for r in results]
        return {"success": True, "result": f"Stored memories ({len(results)}):\n" + "\n".join(parts)}

    registry.register(Tool(
        name="list_memories",
        description="List all stored memories. Optionally filter by category: user_preference, app_knowledge, device_info, learned_procedure, contact, general.",
        parameters=[
            ToolParameter("category", "Filter by category (leave empty for all)", required=False, default=""),
            ToolParameter("limit", "Max number of memories to show", type="integer", required=False, default=20),
        ],
        execute_fn=list_memories,
        category="memory",
    ))

    def ask_user(question: str) -> Dict[str, Any]:
        """Ask the user a question (result will be provided via the next user message)."""
        return {"success": True, "result": f"[ASKING USER]: {question}", "needs_user_input": True}

    registry.register(Tool(
        name="ask_user",
        description="Ask the user a clarifying question when you need more information to proceed.",
        parameters=[
            ToolParameter("question", "The question to ask the user"),
        ],
        execute_fn=ask_user,
        category="utility",
    ))

    # ── Raw ADB (Manual Fallback) ───────────────────────────────

    def run_adb(command: str) -> Dict[str, Any]:
        """Run a raw ADB shell command directly on the device. Use when higher-level tools fail."""
        try:
            output = adb.shell(command, timeout=15)
            return {"success": True, "result": output if output else "(no output)"}
        except Exception as e:
            return {"success": False, "result": f"ADB error: {str(e)}", "error": str(e)}

    if has("raw_shell"):
        registry.register(Tool(
            name="run_adb",
            description="Run a raw device shell command on the device. Use only as a last-resort fallback when higher-level tools fail.",
            parameters=[
                ToolParameter("command", "Shell command to execute on the device (without any host-side prefix)"),
            ],
            execute_fn=run_adb,
            category="manual",
        ))

    def run_intent(action: str, data: str = "", extras: str = "", package: str = "", component: str = "") -> Dict[str, Any]:
        """Launch an Android intent directly. Powerful fallback for opening apps/activities."""
        cmd_parts = ["am start"]
        if action:
            cmd_parts.append(f"-a {action}")
        if data:
            cmd_parts.append(f'-d "{data}"')
        if package:
            cmd_parts.append(f"-n {package}")
            if component:
                cmd_parts[-1] = f"-n {package}/{component}"
        if extras:
            cmd_parts.append(extras)

        cmd = " ".join(cmd_parts)
        try:
            output = adb.shell(cmd, timeout=10)
            return {"success": True, "result": f"Intent sent: {cmd}\nOutput: {output}"}
        except Exception as e:
            return {"success": False, "result": f"Intent failed: {str(e)}", "error": str(e)}

    if has("raw_shell"):
        registry.register(Tool(
            name="run_intent",
            description="Launch an Android intent directly. Useful for opening specific app activities or triggering deep links.",
            parameters=[
                ToolParameter("action", "Intent action (e.g., 'android.intent.action.VIEW', 'android.intent.action.MAIN')", required=False, default=""),
                ToolParameter("data", "Intent data URI (e.g., 'tel:1234567890', 'https://google.com')", required=False, default=""),
                ToolParameter("extras", "Extra flags or arguments as raw string", required=False, default=""),
                ToolParameter("package", "Package name (e.g., 'com.google.android.deskclock')", required=False, default=""),
                ToolParameter("component", "Component or activity class (e.g., '.DeskClock')", required=False, default=""),
            ],
            execute_fn=run_intent,
            category="manual",
        ))
