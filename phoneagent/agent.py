"""
Agent core for PhoneAgent.

Uses an observe -> think -> act loop instead of rigid pre-planned steps.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .adb import ADBController
from .accessibility import AccessibilityParser
from .device_controller import DeviceController, ObservationBundle
from .memory import MemorySystem
from .models import ModelManager
from .phone_tools import register_all_tools
from .planner import TaskPlanner
from .token_manager import TokenManager
from .tools import ToolRegistry
from .vision import VisionAnalyzer


AGENT_SYSTEM_TEMPLATE = """You are PhoneAgent, an autonomous AI that controls an Android phone.

## How You Work
You operate in a reactive loop. Each turn you receive:
1. The user's original goal
2. A fresh observation bundle describing the current device state
3. Your complete action history with success and failure signals
4. Relevant memories
5. The exact tools available right now

You must decide ONE next action based on what you actually observe, not what you assume.

## Device Runtime
__CONTROLLER_CONTEXT__

## Hard Rules
- NEVER invent hidden tools, shell access, or unsupported capabilities.
- ONLY use tools that are explicitly listed below.
- If a capability is unsupported or a tool is missing, adapt using the listed fallback order.
- ALWAYS reason from the current observation bundle first.
- If the last action changed the screen, read the new screen before acting again.
- Navigation paths are not fixed. Menus and layouts can vary by phone and app version.
- If you see the goal is achieved, stop and report success in plain text.
- If you are blocked, explain what is missing or ask the user for help using ask_user.

## Observation Strategy
- Prefer accessibility and tree information when it is available and rich.
- Use screenshot and vision only when the tree is weak, empty, or missing the needed detail.
- If a screenshot analysis is already included and the screen likely has not changed, do not immediately request another screenshot.
- Match elements by their actual visible text, content description, and location.

## Execution Strategy
- Prefer tap_element over tap_coordinates when visible text is available.
- Prefer open_app for launching apps instead of tapping home-screen shortcuts.
- Use wait when an app transition, animation, or network load likely needs time.
- If a tool fails, inspect the failure class and the fresh observation before trying again.
- If the same approach fails repeatedly, choose a different tool or a different target.
- Store durable discoveries such as package names, navigation paths, contacts, or device-specific quirks in memory.

## Decision Format
At each turn, pick ONE of:
A) Call a tool and respond with ONLY a JSON block:
   {"tool": "tool_name", "args": {"param": "value"}}
B) Report to the user in plain text when the goal is done or you need help.

__TOOLS__"""

DIRECT_RESPONSE_SYSTEM = """You are PhoneAgent, a helpful AI assistant for phone control.
The user has asked something that does not require live phone interaction.
Respond naturally and helpfully. If they are asking about capabilities,
explain only the features currently available through the active controller.
If they want to store information in memory, use the store_memory tool."""

MAX_ITERATIONS = 25


class PhoneAgent:
    """Reactive phone control agent."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        device_serial: Optional[str] = None,
        db_path: Optional[str] = None,
        controller: Optional[DeviceController] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, Dict], None]] = None,
        on_tool_result: Optional[Callable[[str, Dict], None]] = None,
    ):
        self._on_status = on_status or (lambda s: None)
        self._on_tool_call = on_tool_call or (lambda n, a: None)
        self._on_tool_result = on_tool_result or (lambda n, r: None)

        self._status("Initializing models...")
        self.models = ModelManager(api_key=api_key)
        self.token_manager = TokenManager()

        self._status("Connecting to device controller...")
        self.controller = controller or ADBController(
            device_serial=device_serial,
            adb_path=os.environ.get("ADB_PATH", "adb"),
        )
        self.adb = self.controller
        self.accessibility = AccessibilityParser(self.controller)
        self.vision = VisionAnalyzer(self.controller, self.models)

        self._status("Loading memory...")
        resolved_db_path = db_path or os.environ.get("PHONEAGENT_DB_PATH")
        self.memory = MemorySystem(resolved_db_path) if resolved_db_path else MemorySystem()

        self._status("Registering tools...")
        self.tools = ToolRegistry()
        self.planner = TaskPlanner(
            self.models,
            self.memory,
            self.tools,
            controller_mode=self.controller.mode,
            capabilities=self.controller.get_capabilities(),
        )
        self._capability_signature = ""
        self._refresh_runtime_configuration(force=True)

        self._task_start_time = 0.0
        self._step_history: List[Dict[str, Any]] = []
        self._last_observation: Optional[ObservationBundle] = None

    def _status(self, msg: str) -> None:
        self._on_status(msg)

    def is_device_connected(self) -> bool:
        return self.controller.is_connected()

    def get_device_info(self) -> Dict[str, Any]:
        return self.controller.get_device_info()

    def get_device_capabilities(self) -> Dict[str, Any]:
        return self.controller.get_capabilities().as_dict()

    def _refresh_runtime_configuration(self, force: bool = False) -> None:
        capabilities = self.controller.get_capabilities()
        signature = json.dumps(capabilities.as_dict(), sort_keys=True, default=str)
        if not force and signature == self._capability_signature:
            return

        registry = ToolRegistry()
        register_all_tools(
            registry=registry,
            controller=self.controller,
            accessibility=self.accessibility,
            memory=self.memory,
            vision_analyzer=self.vision,
        )
        self.tools = registry
        self.planner = TaskPlanner(
            self.models,
            self.memory,
            self.tools,
            controller_mode=self.controller.mode,
            capabilities=capabilities,
        )
        self._capability_signature = signature

    def process_message(self, user_message: str) -> str:
        self._task_start_time = time.time()
        self._step_history = []
        self._last_observation = None
        self._refresh_runtime_configuration()

        self.memory.add_short_term("user", user_message)
        memory_context = self.memory.build_memory_context(user_message)

        needs_phone = self._needs_phone_interaction(user_message)

        if needs_phone:
            if not self.is_device_connected():
                mode_hint = (
                    "Make sure the companion app is connected and authenticated."
                    if self.controller.mode == "companion"
                    else "Please connect your phone and ensure the local controller is available."
                )
                response = f"WARNING: No device is currently reachable. {mode_hint}"
            else:
                response = self._reactive_loop(user_message, memory_context)
                self._extract_memories_after_task(user_message, response)
        else:
            response = self._direct_response(user_message, memory_context)

        self.memory.add_short_term("assistant", response)
        return response

    def _needs_phone_interaction(self, message: str) -> bool:
        msg_lower = message.lower()

        memory_keywords = ["remember", "recall", "forget", "what do you know", "what did i tell"]
        if any(kw in msg_lower for kw in memory_keywords):
            if not any(kw in msg_lower for kw in ["open", "tap", "click", "phone", "app", "screen"]):
                return False

        phone_keywords = [
            "open", "launch", "tap", "click", "swipe", "scroll", "type",
            "send", "call", "message", "sms", "notification", "install",
            "screenshot", "screen", "app", "whatsapp", "instagram",
            "settings", "wifi", "bluetooth", "camera", "brightness",
            "volume", "navigate", "go to", "find", "search", "close",
            "back", "home", "download", "upload", "share", "play",
            "uninstall", "device", "battery", "phone", "check",
        ]
        if any(kw in msg_lower for kw in phone_keywords):
            return True

        question_starters = ["what is", "how does", "can you", "tell me", "explain", "who", "why"]
        if any(msg_lower.startswith(q) for q in question_starters):
            return False

        return True

    def _direct_response(self, message: str, memory_context: str) -> str:
        self._status("Thinking...")

        msg_lower = message.lower()
        if "remember" in msg_lower and ("that" in msg_lower or "my" in msg_lower):
            result = self._handle_memory_store(message)
            if result:
                return result

        if any(kw in msg_lower for kw in ["recall", "what do you know", "what did i tell"]):
            result = self._handle_memory_recall(message)
            if result:
                return result

        messages = [
            {"role": item["role"], "content": item["content"]}
            for item in self.memory.get_short_term(last_n=6)
            if item["role"] in ("user", "assistant")
        ]
        capability_note = self._build_capability_summary(include_metadata=False)
        return self.models.execute(
            messages=messages,
            system=f"{DIRECT_RESPONSE_SYSTEM}\n\n## Current Runtime\n{capability_note}",
            memory_context=memory_context,
        )

    def _handle_memory_store(self, message: str) -> Optional[str]:
        prompt = (
            f"Extract a key-value pair from this request. "
            f"Request: '{message}'\n"
            f'Respond ONLY with JSON: {{"key": "short_key", "value": "the fact", "category": "user_preference"}}\n'
            "Categories: user_preference, app_knowledge, device_info, contact, general"
        )
        try:
            response = self.models.quick_query(prompt)
            data = json.loads(response.strip().strip("`").strip("json").strip())
            self.memory.store(data["key"], data["value"], data.get("category", "general"), source="user")
            return f"Remembered: **{data['key']}** -> {data['value']}"
        except Exception:
            return None

    def _handle_memory_recall(self, message: str) -> Optional[str]:
        results = self.memory.recall(message, top_k=5)
        if not results:
            return "I don't have any relevant memories stored. Tell me things and I'll remember them!"
        parts = ["Here's what I remember:\n"]
        for result in results:
            parts.append(f"* **{result['key']}**: {result['value']}  `[{result['category']}]`")
        return "\n".join(parts)

    def _reactive_loop(self, user_goal: str, memory_context: str) -> str:
        for iteration in range(MAX_ITERATIONS):
            self._refresh_runtime_configuration()
            tools_desc = self.tools.format_for_llm(compact=True)
            system = AGENT_SYSTEM_TEMPLATE.replace("__TOOLS__", tools_desc).replace(
                "__CONTROLLER_CONTEXT__",
                self._build_controller_context(),
            )
            self._status(f"Observing screen (step {iteration + 1})...")
            observation = self._observe_device(include_vision_fallback=True)

            user_prompt = self._build_reactive_prompt(
                user_goal=user_goal,
                observation=observation,
                memory_context=memory_context,
                iteration=iteration,
            )

            self._status(f"Deciding next action (step {iteration + 1})...")
            try:
                if iteration == 0:
                    response = self.models.reason(
                        messages=[{"role": "user", "content": user_prompt}],
                        system=system,
                    )
                else:
                    response = self.models.execute(
                        messages=[{"role": "user", "content": user_prompt}],
                        system=system,
                    )
            except Exception as exc:
                self._status(f"Model error: {exc}")
                self._step_history.append({
                    "step": iteration + 1,
                    "tool": "_model_call",
                    "args": {},
                    "result": f"Model error: {str(exc)[:200]}",
                    "success": False,
                    "failure_class": "model_error",
                })
                if iteration >= 2:
                    self._record_episode(user_goal, f"Model error: {exc}")
                    return f"WARNING: Hit a model error: {exc}\n\nProgress so far:\n{self._summarize_history()}"
                continue

            tool_call, _ = self.tools.parse_response_and_text(response)
            if tool_call is None:
                self._record_episode(user_goal, response)
                return response.strip() if response.strip() else self._fallback_response(user_goal)

            tool_name, tool_args = tool_call
            action_sig = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"

            prev_success = None
            for step in self._step_history:
                step_sig = f"{step['tool']}:{json.dumps(step.get('args', {}), sort_keys=True)}"
                if step_sig == action_sig and step.get("success"):
                    prev_success = step
                    break

            if prev_success:
                self._status(f"Already did '{tool_name}' - returning cached result")
                self._step_history.append({
                    "step": iteration + 1,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": (
                        f"ALREADY DONE (cached from step {prev_success['step']}): "
                        f"{prev_success['result'][:300]}. Choose a different action."
                    ),
                    "success": False,
                    "failure_class": "duplicate_action",
                })
                continue

            repeat_count = sum(
                1
                for step in self._step_history
                if f"{step['tool']}:{json.dumps(step.get('args', {}), sort_keys=True)}" == action_sig
                and not step.get("success")
            )
            if repeat_count >= 1:
                consecutive_blocks = 0
                for step in reversed(self._step_history):
                    if any(tag in step.get("result", "") for tag in ("BLOCKED", "BANNED", "ALREADY DONE")):
                        consecutive_blocks += 1
                    else:
                        break

                if consecutive_blocks >= 3:
                    self._status("Agent stuck in loop - stopping and reporting")
                    self._record_episode(user_goal, "Stuck in loop, bailed out")
                    return (
                        f"WARNING: I got stuck trying to complete this task. "
                        f"I kept attempting `{tool_name}` without making progress.\n\n"
                        f"What I tried:\n{self._summarize_history()}\n\n"
                        "Could you give me more specific instructions or a different goal?"
                    )

                self._status(f"Loop detected! '{tool_name}' blocked - must try a different approach")
                self._step_history.append({
                    "step": iteration + 1,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": (
                        f"BANNED: {tool_name}({tool_args}) already failed before. "
                        "Choose a completely different tool or target."
                    ),
                    "success": False,
                    "failure_class": "loop_detected",
                })
                continue

            self._status(f"Executing: {tool_name}")
            self._on_tool_call(tool_name, tool_args)

            coerced_args = self._coerce_args(tool_name, tool_args)
            result = self.tools.execute_tool(tool_name, **coerced_args)

            post_observation = None
            if self.is_device_connected():
                try:
                    post_observation = self._observe_device(include_vision_fallback=False)
                except Exception:
                    post_observation = None

            enriched_result = self._enrich_tool_result(result, observation, post_observation)
            self._on_tool_result(tool_name, enriched_result)

            step_record = {
                "step": iteration + 1,
                "tool": tool_name,
                "args": coerced_args,
                "result": enriched_result.get("result", "")[:400],
                "success": enriched_result.get("success", False),
                "state": observation.accessibility_summary[:1000],
                "observation_source": observation.source,
                "screen_signature_before": observation.screen_signature,
                "package_before": observation.current_package,
            }
            if post_observation:
                step_record["screen_signature_after"] = post_observation.screen_signature
                step_record["package_after"] = post_observation.current_package
                step_record["screen_changed"] = (
                    observation.screen_signature != post_observation.screen_signature
                )
            metadata = enriched_result.get("metadata", {})
            if metadata.get("failure_class"):
                step_record["failure_class"] = metadata["failure_class"]
            if enriched_result.get("error"):
                step_record["error"] = enriched_result["error"]
            if enriched_result.get("error_type"):
                step_record["error_type"] = enriched_result["error_type"]
            self._step_history.append(step_record)

            if enriched_result.get("success") and len(self._step_history) >= 2:
                prev = self._step_history[-2]
                if not prev.get("success") and prev["tool"] == tool_name:
                    learning_key = (
                        f"learned:{tool_name}:{json.dumps(prev.get('args', {}), sort_keys=True)[:80]}"
                    )
                    learning_val = (
                        f"Failed with {prev.get('args', {})}. "
                        f"Worked with {coerced_args}. Result: {enriched_result.get('result', '')[:120]}"
                    )
                    self.memory.store(
                        learning_key,
                        learning_val,
                        "learned_procedure",
                        importance=7,
                        source="correction",
                    )

            if enriched_result.get("needs_user_input"):
                self._record_episode(user_goal, enriched_result["result"])
                return enriched_result["result"]

            time.sleep(0.3)

        self._record_episode(user_goal, "Hit max iterations")
        return (
            f"WARNING: Reached the step limit ({MAX_ITERATIONS}). "
            f"I may not have fully completed the task. Here's what I did:\n{self._summarize_history()}"
        )

    def _build_controller_context(self) -> str:
        capabilities = self.controller.get_capabilities()
        supported = ", ".join(capabilities.supported_features()) or "(none)"
        unsupported = ", ".join(capabilities.unsupported_features()) or "(none)"
        if self.controller.mode == "companion":
            fallback_order = (
                "1. Accessibility tree\n"
                "2. Screenshot and vision if the tree is weak\n"
                "3. Global actions or app intents via the listed tools\n"
                "4. Ask the user if permissions or context are missing"
            )
            mode_note = (
                "You are controlling the phone through a companion app bridge. "
                "Do not assume shell access, ADB, or host filesystem access unless a tool explicitly provides it."
            )
        else:
            fallback_order = (
                "1. Accessibility tree\n"
                "2. Screenshot and vision if the tree is weak\n"
                "3. Higher-level app and navigation tools\n"
                "4. Manual tools only if they are explicitly listed"
            )
            mode_note = (
                "You are using the local controller runtime. "
                "Manual tools may exist, but only rely on them if they are explicitly listed."
            )
        return (
            f"- Mode: {self.controller.mode}\n"
            f"- Supported capabilities: {supported}\n"
            f"- Unsupported capabilities: {unsupported}\n"
            f"- Runtime note: {mode_note}\n"
            f"- Preferred fallback order:\n{fallback_order}"
        )

    def _build_capability_summary(self, include_metadata: bool = True) -> str:
        capabilities = self.controller.get_capabilities()
        lines = [
            f"- Mode: {self.controller.mode}",
            f"- Supported: {', '.join(capabilities.supported_features()) or '(none)'}",
            f"- Unsupported: {', '.join(capabilities.unsupported_features()) or '(none)'}",
        ]
        if include_metadata and capabilities.metadata:
            for key, value in sorted(capabilities.metadata.items()):
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _observe_device(self, include_vision_fallback: bool = True) -> ObservationBundle:
        now = time.time()
        package = "unknown"
        activity = ""
        raw_xml = ""
        summary = ""
        source = "accessibility"
        node_count = 0
        focused_element = ""
        metadata: Dict[str, Any] = {}

        try:
            if self.controller.supports("ui_tree"):
                hierarchy = self.controller.dump_ui_hierarchy()
                raw_xml = hierarchy.get("xml", "") or ""
                package = hierarchy.get("package", "unknown") or "unknown"
                activity = hierarchy.get("activity", "") or ""
                node_count = int(hierarchy.get("node_count", 0) or 0)
                focused_element = str(hierarchy.get("focused_element", "") or "")
                metadata.update(hierarchy.get("metadata", {}) or {})

                if raw_xml:
                    elements = self.accessibility.parse_xml(raw_xml)
                    if elements:
                        node_count = node_count or len(elements)
                        summary = self.accessibility.build_screen_summary(elements, max_tokens=1500)

                device_summary = hierarchy.get("summary", "") or ""
                if device_summary and (not summary or "No UI elements" in summary):
                    summary = device_summary

            if package == "unknown":
                try:
                    package = self.controller.get_current_package() or "unknown"
                except Exception:
                    package = "unknown"
            if not activity:
                try:
                    activity = self.controller.get_current_activity() or ""
                except Exception:
                    activity = ""
        except Exception as exc:
            summary = f"[Could not read screen: {str(exc)}]"

        screenshot_analysis = ""
        screenshot_available = self.controller.supports("screenshots")
        summary_is_weak = (not summary) or ("No UI elements" in summary) or (len(summary.strip()) < 50)
        if include_vision_fallback and screenshot_available and summary_is_weak:
            vision_result = self.vision.capture_and_analyze(
                prompt="Describe everything visible on this phone screen. List buttons, text, and interactive elements.",
                max_width=480,
            )
            if vision_result.get("success"):
                screenshot_analysis = vision_result["description"]
                if summary_is_weak:
                    summary = f"[Vision Analysis]\n{screenshot_analysis}"
                    source = "vision"

        signature_source = f"{package}|{activity}|{summary[:800]}|{focused_element}"
        screen_signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()[:12]

        bundle = ObservationBundle(
            current_package=package,
            current_activity=activity,
            accessibility_summary=summary,
            raw_xml=raw_xml,
            screenshot_available=screenshot_available,
            last_screenshot_analysis=screenshot_analysis,
            observed_at=now,
            source=source,
            node_count=node_count,
            focused_element=focused_element,
            screen_signature=screen_signature,
            metadata=metadata,
        )
        self._last_observation = bundle
        return bundle

    def _build_reactive_prompt(
        self,
        user_goal: str,
        observation: ObservationBundle,
        memory_context: str,
        iteration: int,
    ) -> str:
        parts = [f"## User Goal\n{user_goal}"]

        now = datetime.now()
        parts.append(
            "\n## Current Context\n"
            f"- Date: {now.strftime('%A')}, {now.strftime('%Y-%m-%d')}\n"
            f"- Time: {now.strftime('%I:%M %p')} ({now.strftime('%H:%M')})\n"
            f"- Timezone: {now.astimezone().tzinfo}"
        )

        if iteration == 0 and memory_context:
            parts.append(f"\n## Relevant Memories\n{memory_context}")

        parts.append(
            "\n## Observation Bundle\n"
            f"- Source: {observation.source}\n"
            f"- Observed: {datetime.fromtimestamp(observation.observed_at).isoformat()}\n"
            f"- Current package: {observation.current_package}\n"
            f"- Current activity: {observation.current_activity or '(unknown)'}\n"
            f"- Visible node count: {observation.node_count}\n"
            f"- Focused element: {observation.focused_element or '(none)'}\n"
            f"- Screen signature: {observation.screen_signature}"
        )

        if observation.metadata:
            parts.append("### Device-side Metadata")
            for key, value in sorted(observation.metadata.items()):
                parts.append(f"- {key}: {value}")

        if self._step_history:
            parts.append("\n## Action History")
            history_lines = []
            for step in self._step_history:
                icon = "SUCCESS" if step["success"] else "FAIL"
                max_result_len = 500 if step["tool"] in ("take_screenshot", "get_screen_info", "read_screen_text") else 220
                result_text = step["result"][:max_result_len]
                args_brief = ", ".join(
                    f"{k}={repr(v)[:40]}" for k, v in step.get("args", {}).items()
                )
                line = f"  {icon} Step {step['step']}: {step['tool']}({args_brief}) -> {result_text}"
                if step.get("failure_class"):
                    line += f"\n    FAILURE CLASS: {step['failure_class']}"
                if step.get("screen_changed") is not None:
                    line += f"\n    SCREEN CHANGED: {step.get('screen_changed')}"
                if step.get("package_after"):
                    line += f"\n    PACKAGE AFTER: {step['package_after']}"
                if not step["success"] and step.get("error"):
                    line += f"\n    ERROR DETAILS: {step['error'][:220]}"
                history_lines.append(line)
            parts.append("\n".join(history_lines))

            recent = self._step_history[-3:]
            if len(recent) >= 3 and all(not step["success"] for step in recent):
                parts.append("\nWARNING: LAST 3 ACTIONS ALL FAILED. You MUST try a different approach.")
                parts.append(
                    "Prefer: inspect the observation bundle more carefully, use a different listed tool, "
                    "use screenshot and vision only if needed, or ask_user if permissions or context are missing."
                )

            dead_approaches = set()
            for step in self._step_history:
                if not step["success"]:
                    sig = f"{step['tool']}({', '.join(f'{k}={v}' for k, v in step.get('args', {}).items())})"
                    dead_approaches.add(sig)
            if dead_approaches:
                parts.append("\n## Failed Approaches")
                for approach in sorted(dead_approaches):
                    parts.append(f"  - {approach}")
        else:
            parts.append("\n## Action History\n(No actions taken yet - this is your first move)")

        if observation.last_screenshot_analysis and observation.source == "vision":
            parts.append(
                "\n## Current Screen State (vision is primary)\n"
                f"{observation.last_screenshot_analysis[:1000]}\n\n"
                "The accessibility tree is weak or empty here, so rely on the visual description above. "
                "Do not request another screenshot unless the screen likely changed."
            )
        elif observation.last_screenshot_analysis:
            parts.append(
                "\n## Current Screen State (accessibility + vision)\n"
                f"### Accessibility Summary\n{observation.accessibility_summary}\n\n"
                f"### Vision Analysis\n{observation.last_screenshot_analysis[:700]}\n\n"
                "Use the tree first and the screenshot analysis only as supporting context."
            )
        else:
            parts.append(
                "\n## Current Screen State\n"
                f"{observation.accessibility_summary or '[No screen data available]'}"
            )

        parts.append(
            "\n## Your Turn\n"
            "Based on the goal, the observation bundle, and the action history, choose your SINGLE next action. "
            "If the goal is already achieved, respond with a text confirmation. "
            "If you need to act, respond with ONLY a JSON tool call. "
            "Never repeat an action that already appears in failed or blocked history."
        )
        return "\n".join(parts)

    def _enrich_tool_result(
        self,
        result: Dict[str, Any],
        before: ObservationBundle,
        after: Optional[ObservationBundle],
    ) -> Dict[str, Any]:
        enriched = dict(result)
        metadata = dict(enriched.get("metadata") or {})
        metadata.update({
            "controller_mode": self.controller.mode,
            "observation_source": after.source if after else before.source,
            "package_before": before.current_package,
            "screen_signature_before": before.screen_signature,
        })
        if after:
            metadata.update({
                "package_after": after.current_package,
                "screen_signature_after": after.screen_signature,
                "screen_changed": before.screen_signature != after.screen_signature,
            })
        if not enriched.get("success"):
            metadata["failure_class"] = self._classify_failure(enriched)
        enriched["metadata"] = metadata
        if metadata.get("package_after"):
            enriched["package_after"] = metadata["package_after"]
        if "screen_changed" in metadata:
            enriched["screen_changed"] = metadata["screen_changed"]
        return enriched

    def _classify_failure(self, result: Dict[str, Any]) -> str:
        text = " ".join([
            str(result.get("result", "")),
            str(result.get("error_message", "")),
            str(result.get("error", "")),
        ]).lower()
        if "offline" in text or "not reachable" in text or "disconnected" in text:
            return "device_offline"
        if "not support" in text or "unsupported" in text or "unknown tool" in text:
            return "unsupported_capability"
        if "permission" in text or "accessibility" in text or "projection" in text:
            return "permission_missing"
        if "timeout" in text:
            return "timeout"
        if "not found" in text or "could not find" in text or "element not found" in text:
            return "target_not_found"
        if "loop" in text:
            return "loop_detected"
        return "action_failed"

    def _coerce_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = self.tools.get(tool_name)
        if not tool:
            return args

        coerced = {}
        for param in tool.parameters:
            val = args.get(param.name, param.default)
            if val is None:
                if param.required:
                    coerced[param.name] = ""
                continue

            try:
                if param.type == "integer":
                    val = int(val)
                elif param.type == "number":
                    val = float(val)
                elif param.type == "boolean":
                    val = str(val).lower() in ("true", "1", "yes")
                else:
                    val = str(val)
            except (ValueError, TypeError):
                pass

            coerced[param.name] = val
        return coerced

    def _summarize_history(self) -> str:
        if not self._step_history:
            return "(No actions were taken)"
        lines = []
        for step in self._step_history:
            icon = "SUCCESS" if step["success"] else "FAIL"
            lines.append(f"{icon} {step['tool']}: {step['result'][:100]}")
        return "\n".join(lines)

    def _fallback_response(self, user_goal: str) -> str:
        if self._step_history:
            all_ok = all(step["success"] for step in self._step_history)
            if all_ok:
                return f"Done! Completed {len(self._step_history)} actions for: {user_goal}"
            return f"Partially done.\n{self._summarize_history()}"
        return "I wasn't sure how to proceed. Could you give me more details?"

    def _record_episode(self, user_goal: str, response: str) -> None:
        if not self._step_history:
            return
        duration = time.time() - self._task_start_time
        all_success = all(step.get("success", False) for step in self._step_history)
        episode_metadata = {
            "controller_mode": self.controller.mode,
            "capabilities": self.controller.get_capabilities().as_dict(),
            "packages_seen": sorted((
                {
                    step.get("package_before", "")
                    for step in self._step_history
                } | {
                    step.get("package_after", "")
                    for step in self._step_history
                }
            ) - {""}),
            "screen_signatures": sorted((
                {
                    step.get("screen_signature_before", "")
                    for step in self._step_history
                } | {
                    step.get("screen_signature_after", "")
                    for step in self._step_history
                }
            ) - {""}),
        }
        self.memory.record_episode(
            task_description=user_goal,
            steps=self._step_history,
            result=response[:200],
            success=all_success,
            duration=duration,
            metadata=episode_metadata,
        )

    def _extract_memories_after_task(self, user_goal: str, response: str) -> None:
        if not self._step_history:
            return

        history_summary = "\\n".join(
            f"Step {step['step']}: {step['tool']} -> {step.get('result', '')[:100]}"
            for step in self._step_history
        )
        prompt = (
            f"You just completed a phone task.\\n"
            f"User Goal: '{user_goal}'\\n"
            f"Result: '{response}'\\n"
            f"History: \\n{history_summary}\\n\\n"
            "Did you learn any new explicit facts, user preferences, API keys, passwords, PINs, or credentials during this task?\\n"
            "If YES, extract them. If NO, return an empty array.\\n"
            "Respond ONLY with a JSON array of objects:\\n"
            '[{"key": "short_descriptive_key", "value": "the extracted info", "category": "user_preference|app_knowledge|general"}]'
        )

        try:
            extraction = self.models.quick_query(prompt)
            data = json.loads(extraction.strip().strip("`").strip("json").strip())
            if isinstance(data, list):
                for item in data:
                    if "key" in item and "value" in item:
                        self.memory.store(
                            item["key"],
                            item["value"],
                            item.get("category", "general"),
                            importance=7,
                            source="auto_extract",
                        )
                        self._status(f"Dynamically learned: {item['key']}")
        except Exception as exc:
            self._status(f"Memory extraction failed (silently ignored): {exc}")

    def execute_direct_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        kwargs = self._coerce_args(tool_name, kwargs)
        return self.tools.execute_tool(tool_name, **kwargs)

    def get_memory_stats(self) -> Dict[str, Any]:
        return self.memory.get_memory_stats()

    def get_all_memories(self) -> List[Dict[str, Any]]:
        return self.memory.get_all_memories()

    def get_recent_tasks(self, n: int = 5) -> List[Dict[str, Any]]:
        return self.memory.get_recent_episodes(n)

    def shutdown(self) -> None:
        self._status("Shutting down...")
        self.memory.close()
