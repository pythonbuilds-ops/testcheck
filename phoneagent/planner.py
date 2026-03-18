"""
Task Planner — Decomposes complex user requests into executable steps.

Uses GPT-OSS-120b for intelligent planning and step breakdown,
with replanning support when steps fail.
"""

import json
import re
from typing import List, Dict, Any, Optional

from .device_controller import DeviceCapabilities
from .models import ModelManager
from .memory import MemorySystem
from .tools import ToolRegistry


# ── Step Schema ─────────────────────────────────────────────────

PLAN_EXAMPLE = """{
  "plan": [
    {
      "step": 1,
      "description": "Open WhatsApp",
      "tool": "open_app",
      "args": {"name": "WhatsApp"},
      "expected": "WhatsApp opens and shows chat list",
      "fallback": "Try with package name com.whatsapp"
    },
    {
      "step": 2,
      "description": "Find and tap the contact 'Mom'",
      "tool": "scroll_to_find",
      "args": {"text": "Mom"},
      "expected": "Contact 'Mom' is visible",
      "fallback": "Use search feature to find contact"
    }
  ]
}"""

PLANNING_SYSTEM = """You are the planning engine of a phone control agent.
Your job is to decompose user requests into a series of actionable steps.

RULES:
1. Each step must use exactly ONE tool.
2. Steps should be ordered logically — dependencies come first.
3. Include expected results so the executor can verify success.
4. Include fallback strategies for steps that might fail.
5. Be specific: use exact UI text, app names, coordinates when known.
6. Prefer accessibility-based tools (tap_element, get_screen_info) over vision (take_screenshot).
7. Use get_screen_info before interacting to understand the current state.
8. Add wait steps between actions that trigger loading/transitions.
9. Only use tools that are explicitly listed. Never invent hidden shell access or unsupported capabilities.

Runtime context:
{runtime_context}

{tools_description}

Respond ONLY with a JSON plan in this format:
{plan_example}

Do not include any text outside the JSON block."""

REPLAN_SYSTEM = """You are replanning a phone action sequence because a step failed.

Original plan: {original_plan}
Failed at step {failed_step}: {error}
Current screen state: {screen_state}
Runtime context: {runtime_context}

Create a revised plan starting from the current state. Adjust your approach based on the error.
You may need to try a different strategy or insert additional steps.

Respond ONLY with a JSON plan in the same format as before."""


class TaskPlanner:
    """Decomposes complex tasks into executable step sequences."""

    def __init__(
        self,
        model_manager: ModelManager,
        memory: MemorySystem,
        tool_registry: ToolRegistry,
        controller_mode: str = "local",
        capabilities: Optional[DeviceCapabilities] = None,
    ):
        self.models = model_manager
        self.memory = memory
        self.tools = tool_registry
        self.controller_mode = controller_mode
        self.capabilities = capabilities or DeviceCapabilities()

    def _runtime_context(self) -> str:
        supported = ", ".join(self.capabilities.supported_features()) or "(none)"
        unsupported = ", ".join(self.capabilities.unsupported_features()) or "(none)"
        if self.controller_mode == "companion":
            mode_note = (
                "This runtime uses a companion app bridge. Do not suggest ADB, shell, host filesystem, "
                "or package-manager tricks unless those capabilities are explicitly exposed by tools."
            )
        else:
            mode_note = (
                "This runtime uses the local controller. Manual tools may exist, but only if they appear in the tool list."
            )
        return (
            f"mode={self.controller_mode}; supported={supported}; unsupported={unsupported}; {mode_note}"
        )

    def plan_task(
        self,
        user_request: str,
        screen_context: Optional[str] = None,
        memory_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Create an execution plan for a user request.

        Args:
            user_request: The user's task description.
            screen_context: Current screen state from accessibility tree.
            memory_context: Relevant memory context.

        Returns:
            List of step dicts with tool/args/expected/fallback.
        """
        # Build system prompt with tools
        tools_desc = self.tools.format_for_llm(compact=True)
        system = PLANNING_SYSTEM.format(
            tools_description=tools_desc,
            plan_example=PLAN_EXAMPLE,
            runtime_context=self._runtime_context(),
        )

        # Check for similar past tasks
        episodes = self.memory.recall_similar_task(user_request, top_k=1)
        episode_context = ""
        if episodes and episodes[0].get("success"):
            ep = episodes[0]
            episode_context = f"\n\nA similar task was done before: '{ep['task_description']}'\nSteps used: {json.dumps(ep['steps'][:5])}\nResult: {ep['result']}"

        user_msg = f"User request: {user_request}{episode_context}"

        messages = [{"role": "user", "content": user_msg}]

        # Use reasoner (GPT-OSS-120b) for planning
        response = self.models.reason(
            messages=messages,
            system=system,
            screen_data=screen_context,
            memory_context=memory_context,
        )

        return self._parse_plan(response)

    def replan(
        self,
        original_plan: List[Dict[str, Any]],
        failed_step: int,
        error: str,
        screen_state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Create a revised plan when a step fails.

        Args:
            original_plan: The original plan that failed.
            failed_step: Step number that failed (1-indexed).
            error: Error message/description.
            screen_state: Current screen context.

        Returns:
            Revised plan from current state forward.
        """
        tools_desc = self.tools.format_for_llm(compact=True)
        system = REPLAN_SYSTEM.format(
            original_plan=json.dumps(original_plan[:10]),  # Limit size
            failed_step=failed_step,
            error=error,
            screen_state=screen_state or "Unknown",
            runtime_context=self._runtime_context(),
        ) + f"\n\n{tools_desc}"

        messages = [{"role": "user", "content": "Create a revised plan to complete the task."}]

        response = self.models.reason(
            messages=messages,
            system=system,
        )

        return self._parse_plan(response)

    def should_use_vision(
        self,
        step: Dict[str, Any],
        accessibility_result: str,
    ) -> bool:
        """
        Decide if vision analysis is needed for a step.

        Vision is used when:
        1. Accessibility tree returned no useful elements
        2. Step involves visual verification
        3. Step explicitly needs vision

        Args:
            step: Current step dict.
            accessibility_result: Text from accessibility tree analysis.

        Returns:
            True if vision should be used.
        """
        # If accessibility returned nothing useful
        if not accessibility_result or "No UI elements" in accessibility_result:
            return True

        # If step requires visual verification
        tool = step.get("tool", "")
        if tool in ["take_screenshot", "verify_action"] and self.capabilities.screenshots:
            return True

        # If step description mentions visual terms
        desc = step.get("description", "").lower()
        visual_keywords = ["image", "photo", "icon", "color", "visible", "appears", "look", "see"]
        if any(kw in desc for kw in visual_keywords):
            return True

        return False

    def create_simple_plan(self, tool_name: str, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create a single-step plan for simple tool calls."""
        return [{
            "step": 1,
            "description": f"Execute {tool_name}",
            "tool": tool_name,
            "args": args,
            "expected": "Action completes successfully",
            "fallback": "Retry once",
        }]

    def _parse_plan(self, response: str) -> List[Dict[str, Any]]:
        """
        Parse plan JSON from model response.

        Handles various response formats robustly.
        """
        # Try to extract JSON from code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return data.get("plan", [data] if "tool" in data else [])
            except json.JSONDecodeError:
                pass

        # Try raw JSON parse
        try:
            data = json.loads(response)
            if isinstance(data, dict):
                return data.get("plan", [data] if "tool" in data else [])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Try to find any JSON object in the response
        brace_depth = 0
        start = None
        for i, ch in enumerate(response):
            if ch == '{':
                if brace_depth == 0:
                    start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and start is not None:
                    try:
                        data = json.loads(response[start:i+1])
                        if "plan" in data:
                            return data["plan"]
                        if "tool" in data:
                            return [data]
                    except json.JSONDecodeError:
                        pass
                    start = None

        # Fallback: create a generic plan
        return [{
            "step": 1,
            "description": "Could not parse plan. Using get_screen_info to assess.",
            "tool": "get_screen_info",
            "args": {},
            "expected": "Screen info retrieved",
            "fallback": "Ask user for clarification",
        }]
