"""Quick verification tests for PhoneAgent subsystems."""

import sys
import os

# Ensure we can import the package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0


def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  PASS  {name}")
        passed += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        failed += 1


# ── Token Manager Tests ────────────────────────────────────────

def test_token_count():
    from phoneagent.token_manager import TokenManager
    tm = TokenManager()
    assert tm.count_tokens("Hello world") > 0
    assert tm.count_tokens("") == 0

def test_token_trim():
    from phoneagent.token_manager import TokenManager
    tm = TokenManager()
    # Use large enough messages to exceed the 200-token budget
    msgs = [{"role": "user", "content": "This is a long message number " + str(i) + " with enough content to consume tokens. " * 3} for i in range(20)]
    trimmed = tm.trim_messages(msgs, max_tokens=200)
    assert len(trimmed) < len(msgs), f"Expected fewer messages but got {len(trimmed)} from {len(msgs)}"

def test_token_build_request():
    from phoneagent.token_manager import TokenManager
    tm = TokenManager()
    msgs = [{"role": "user", "content": "test"}]
    built = tm.build_request("System", msgs, "screen", "memory")
    assert len(built) >= 2
    assert built[0]["role"] == "system"

test("TokenManager.count_tokens", test_token_count)
test("TokenManager.trim_messages", test_token_trim)
test("TokenManager.build_request", test_token_build_request)


# ── Memory System Tests ────────────────────────────────────────

def test_memory_store_recall():
    from phoneagent.memory import MemorySystem
    m = MemorySystem(":memory:")
    m.store("fav_color", "blue", "user_preference")
    results = m.recall("color")
    assert len(results) > 0
    assert results[0]["value"] == "blue"
    m.close()

def test_memory_episodes():
    from phoneagent.memory import MemorySystem
    m = MemorySystem(":memory:")
    m.record_episode("test task", [{"action": "test"}], "done", True, 1.0)
    eps = m.get_recent_episodes(5)
    assert len(eps) == 1
    assert eps[0]["task_description"] == "test task"
    m.close()

def test_memory_auto_discover():
    from phoneagent.memory import MemorySystem
    m = MemorySystem(":memory:")
    m.auto_discover("chrome_pkg", "com.android.chrome", "app_knowledge")
    results = m.recall("chrome")
    assert len(results) > 0
    m.close()

def test_memory_context():
    from phoneagent.memory import MemorySystem
    m = MemorySystem(":memory:")
    m.store("wifi_password", "secret123", "device_info")
    ctx = m.build_memory_context("wifi password")
    assert "secret123" in ctx
    m.close()

def test_memory_forget():
    from phoneagent.memory import MemorySystem
    m = MemorySystem(":memory:")
    m.store("temp", "data", "general")
    assert m.forget("temp") == True
    results = m.recall("temp")
    assert len(results) == 0
    m.close()

test("Memory.store_recall", test_memory_store_recall)
test("Memory.episodes", test_memory_episodes)
test("Memory.auto_discover", test_memory_auto_discover)
test("Memory.build_context", test_memory_context)
test("Memory.forget", test_memory_forget)


# ── Tool Registry Tests ────────────────────────────────────────

def test_tool_register():
    from phoneagent.tools import ToolRegistry, Tool, ToolParameter
    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="Echo test",
        parameters=[ToolParameter("msg", "message")],
        execute_fn=lambda msg="": {"success": True, "result": f"Echo: {msg}"},
    ))
    assert len(reg.list_tools()) == 1
    result = reg.execute_tool("echo", msg="hi")
    assert result["success"] == True
    assert "hi" in result["result"]

def test_tool_parse():
    from phoneagent.tools import ToolRegistry
    reg = ToolRegistry()
    response = 'Do this: {"tool": "tap_element", "args": {"text": "OK"}}'
    parsed = reg.parse_tool_call(response)
    assert parsed is not None
    assert parsed[0] == "tap_element"
    assert parsed[1]["text"] == "OK"

def test_tool_unknown():
    from phoneagent.tools import ToolRegistry
    reg = ToolRegistry()
    result = reg.execute_tool("nonexistent")
    assert result["success"] == False

def test_tool_format():
    from phoneagent.tools import ToolRegistry, Tool, ToolParameter
    reg = ToolRegistry()
    reg.register(Tool(name="test", description="Test", parameters=[]))
    fmt = reg.format_for_llm()
    assert "test" in fmt

test("ToolRegistry.register_execute", test_tool_register)
test("ToolRegistry.parse_tool_call", test_tool_parse)
test("ToolRegistry.unknown_tool", test_tool_unknown)
test("ToolRegistry.format_for_llm", test_tool_format)


# ── Accessibility Parser Tests ──────────────────────────────────

def test_accessibility_parse():
    from phoneagent.accessibility import AccessibilityParser, UIElement
    # Test XML parsing without ADB
    from phoneagent.accessibility import AccessibilityParser
    
    # Create a mock parser (won't connect to device)
    class MockADB:
        pass
    
    parser = AccessibilityParser(MockADB())
    
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy>
        <node index="0" text="Settings" resource-id="com.android.settings:id/title"
              class="android.widget.TextView" package="com.android.settings"
              content-desc="" checkable="false" checked="false" clickable="true"
              enabled="true" focusable="true" focused="false" scrollable="false"
              long-clickable="false" password="false" selected="false"
              bounds="[0,0][540,96]" />
        <node index="1" text="WiFi" resource-id=""
              class="android.widget.TextView" package="com.android.settings"
              content-desc="WiFi settings" checkable="false" checked="false" clickable="true"
              enabled="true" focusable="false" focused="false" scrollable="false"
              long-clickable="false" password="false" selected="false"
              bounds="[0,96][540,192]" />
    </hierarchy>'''
    
    elements = parser.parse_xml(xml)
    assert len(elements) == 2
    assert elements[0].text == "Settings"
    assert elements[0].clickable == True
    assert elements[0].center == (270, 48)
    
    # Test find
    matches = parser.find_elements(elements, text="WiFi")
    assert len(matches) == 1
    assert matches[0].content_desc == "WiFi settings"
    
    # Test summary
    summary = parser.build_screen_summary(elements)
    assert "Settings" in summary
    
    # Test text extraction
    text = parser.get_full_screen_text(elements)
    assert "Settings" in text
    assert "WiFi" in text

test("AccessibilityParser.parse_and_query", test_accessibility_parse)


# ── ADB Controller Tests (no device needed) ────────────────────

def test_adb_build_cmd():
    from phoneagent.adb import ADBController
    ctrl = ADBController(device_serial="test123")
    cmd = ctrl._build_cmd("devices")
    assert "test123" in cmd
    assert "-s" in cmd

def test_adb_no_serial():
    from phoneagent.adb import ADBController
    ctrl = ADBController()
    cmd = ctrl._build_cmd("devices")
    assert "-s" not in cmd

test("ADBController.build_cmd_with_serial", test_adb_build_cmd)
test("ADBController.build_cmd_no_serial", test_adb_no_serial)


# ── Summary ────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
if failed == 0:
    print("ALL TESTS PASSED!")
else:
    print(f"SOME TESTS FAILED!")
    sys.exit(1)
