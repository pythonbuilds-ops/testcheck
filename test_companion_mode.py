import unittest
import asyncio
from unittest.mock import patch

from phoneagent.accessibility import AccessibilityParser
from phoneagent.agent import AGENT_SYSTEM_TEMPLATE, PhoneAgent
from phoneagent.companion import DeviceSessionManager
from phoneagent.device_controller import DeviceCapabilities, DeviceController
from phoneagent.memory import MemorySystem
from phoneagent.phone_tools import register_all_tools
from phoneagent.planner import TaskPlanner
from phoneagent.tools import ToolRegistry


class FakeController(DeviceController):
    def __init__(self, mode: str = "companion", capabilities: DeviceCapabilities | None = None):
        super().__init__(mode=mode, capabilities=capabilities or DeviceCapabilities(
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
            metadata={"transport": mode},
        ))

    def is_connected(self) -> bool:
        return True

    def get_device_serial(self):
        return "fake-device"

    def dump_ui_hierarchy(self):
        return {
            "xml": "<hierarchy><node text=\"Settings\" clickable=\"true\" bounds=\"[0,0][100,100]\" /></hierarchy>",
            "package": "com.android.settings",
            "activity": "MainActivity",
            "node_count": 1,
            "focused_element": "Settings",
            "summary": "Settings button",
        }

    def get_current_activity(self) -> str:
        return "MainActivity"

    def get_current_package(self) -> str:
        return "com.android.settings"

    def tap(self, x: int, y: int) -> str:
        return ""

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> str:
        return ""

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        return ""

    def swipe_direction(self, direction: str, distance_ratio: float = 0.5) -> str:
        return ""

    def input_text(self, text: str) -> str:
        return ""

    def key_event(self, keycode: str) -> str:
        return ""

    def screenshot_base64(self, max_width: int = 720, quality: int = 60) -> str:
        return "ZmFrZQ=="

    def launch_app(self, package: str) -> str:
        return ""

    def stop_app(self, package: str) -> str:
        return ""

    def list_packages(self, filter_str=None):
        return ["com.android.settings", "com.whatsapp"]

    def install_app(self, apk_path: str) -> str:
        return ""

    def push_file(self, local_path: str, remote_path: str) -> str:
        return ""

    def pull_file(self, remote_path: str, local_path: str) -> str:
        return ""

    def get_device_info(self):
        return {"model": "Fake", "android_version": "14", "screen_width": 1080, "screen_height": 2400}

    def make_call(self, phone_number: str) -> str:
        return ""

    def send_sms(self, phone_number: str, message: str) -> str:
        return ""

    def open_url(self, url: str) -> str:
        return ""

    def get_notifications(self) -> str:
        return "android.title=Test"

    def expand_notifications(self) -> str:
        return ""

    def collapse_notifications(self) -> str:
        return ""

    def set_clipboard(self, text: str) -> str:
        return ""

    def open_settings(self, settings_page: str = "") -> str:
        return ""


class MutableFakeController(FakeController):
    def set_capabilities(self, capabilities: DeviceCapabilities):
        self._capabilities = capabilities


class DummyModelManager:
    def __init__(self, api_key=None):
        self.api_key = api_key

    def execute(self, *args, **kwargs):
        return ""

    def reason(self, *args, **kwargs):
        return ""

    def quick_query(self, *args, **kwargs):
        return "[]"


class DummyVisionAnalyzer:
    def __init__(self, controller, models):
        self.controller = controller
        self.models = models

    def capture_and_analyze(self, *args, **kwargs):
        return {"success": True, "description": "Settings screen"}

    def read_screen_text(self, *args, **kwargs):
        return {"success": True, "result": "Settings"}


class DummyWebSocket:
    def __init__(self):
        self.payloads = []

    async def send_json(self, payload):
        self.payloads.append(payload)


class CompanionModeTests(unittest.TestCase):
    def test_companion_tool_registration_hides_adb_only_tools(self):
        registry = ToolRegistry()
        controller = FakeController()
        register_all_tools(
            registry=registry,
            controller=controller,
            accessibility=AccessibilityParser(controller),
            memory=MemorySystem(":memory:"),
            vision_analyzer=DummyVisionAnalyzer(controller, DummyModelManager()),
        )
        tool_names = set(registry.list_tool_names())
        self.assertNotIn("run_adb", tool_names)
        self.assertNotIn("install_apk", tool_names)
        self.assertNotIn("file_transfer", tool_names)
        self.assertNotIn("close_app", tool_names)
        self.assertIn("open_app", tool_names)
        self.assertIn("tap_element", tool_names)

    def test_planner_runtime_context_mentions_companion_limits(self):
        planner = TaskPlanner(
            model_manager=DummyModelManager(),
            memory=MemorySystem(":memory:"),
            tool_registry=ToolRegistry(),
            controller_mode="companion",
            capabilities=FakeController().get_capabilities(),
        )
        context = planner._runtime_context()
        self.assertIn("companion app bridge", context)
        self.assertIn("raw_shell", context)

    @patch("phoneagent.agent.ModelManager", DummyModelManager)
    @patch("phoneagent.agent.VisionAnalyzer", DummyVisionAnalyzer)
    def test_agent_prompt_avoids_stale_adb_instructions(self):
        agent = PhoneAgent(
            api_key="test",
            db_path=":memory:",
            controller=FakeController(),
        )
        system = AGENT_SYSTEM_TEMPLATE.replace("__TOOLS__", agent.tools.format_for_llm(compact=True)).replace(
            "__CONTROLLER_CONTEXT__",
            agent._build_controller_context(),
        )
        self.assertIn("companion app bridge", system)
        self.assertNotIn("run_adb", system)
        self.assertNotIn("adb shell", system.lower())

    @patch("phoneagent.agent.ModelManager", DummyModelManager)
    @patch("phoneagent.agent.VisionAnalyzer", DummyVisionAnalyzer)
    def test_observation_bundle_contains_capability_aware_fields(self):
        agent = PhoneAgent(
            api_key="test",
            db_path=":memory:",
            controller=FakeController(),
        )
        observation = agent._observe_device(include_vision_fallback=False)
        self.assertEqual(observation.current_package, "com.android.settings")
        self.assertEqual(observation.current_activity, "MainActivity")
        self.assertEqual(observation.source, "accessibility")
        self.assertEqual(observation.node_count, 1)
        self.assertEqual(observation.focused_element, "Settings")
        self.assertTrue(observation.screen_signature)

    def test_device_session_manager_handles_timeout_and_reconnect(self):
        manager = DeviceSessionManager(auth_token="secret", heartbeat_timeout=0.05)
        loop = asyncio.new_event_loop()
        try:
            first_socket = DummyWebSocket()
            first_session = manager.register_session(
                device_id="device-1",
                websocket=first_socket,
                loop=loop,
                capabilities={"ui_tree": True, "screenshots": True, "raw_shell": False},
                device_info={"model": "Fake One"},
                metadata={"transport": "companion"},
            )
            self.assertTrue(manager.verify_token("secret"))
            self.assertTrue(manager.is_connected("device-1"))
            self.assertEqual(manager.get_device_info("device-1").get("model"), "Fake One")

            first_session.last_heartbeat -= 1.0
            self.assertFalse(manager.is_connected("device-1"))

            second_socket = DummyWebSocket()
            manager.register_session(
                device_id="device-1",
                websocket=second_socket,
                loop=loop,
                capabilities={"ui_tree": True, "screenshots": True, "raw_shell": False},
                device_info={"model": "Fake Two"},
                metadata={"transport": "companion"},
            )
            self.assertTrue(manager.is_connected("device-1"))
            self.assertEqual(manager.get_device_info("device-1").get("model"), "Fake Two")
        finally:
            loop.close()

    @patch("phoneagent.agent.ModelManager", DummyModelManager)
    @patch("phoneagent.agent.VisionAnalyzer", DummyVisionAnalyzer)
    def test_agent_refreshes_toolset_when_capabilities_change(self):
        controller = MutableFakeController()
        agent = PhoneAgent(
            api_key="test",
            db_path=":memory:",
            controller=controller,
        )
        self.assertIn("take_screenshot", set(agent.tools.list_tool_names()))

        controller.set_capabilities(DeviceCapabilities(
            ui_tree=True,
            screenshots=False,
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
        ))
        agent._refresh_runtime_configuration()
        self.assertNotIn("take_screenshot", set(agent.tools.list_tool_names()))


if __name__ == "__main__":
    unittest.main()
