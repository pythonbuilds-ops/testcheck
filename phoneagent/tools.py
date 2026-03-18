"""
Tool Registry — Defines tool interface and registration system.

Each tool has a name, description, parameters schema, and execute method.
The registry formats tools for LLM consumption and parses tool calls
from LLM responses.
"""

import json
import re
from typing import Callable, Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ToolParameter:
    """Describes a single parameter for a tool."""
    name: str
    description: str
    type: str = "string"  # string, integer, number, boolean
    required: bool = True
    enum: Optional[List[str]] = None
    default: Any = None


@dataclass
class Tool:
    """
    Represents a callable tool available to the agent.

    Attributes:
        name: Unique tool name (snake_case).
        description: Human-readable description of what the tool does.
        parameters: List of ToolParameter definitions.
        execute_fn: The function to call when executing.
        category: Tool category for grouping.
    """
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)
    execute_fn: Optional[Callable] = None
    category: str = "general"

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute this tool with the given arguments.

        Returns:
            Dict with 'success' (bool), 'result' (str), and optionally 'error' (str) keys.
        """
        if not self.execute_fn:
            return {"success": False, "result": f"Tool '{self.name}' has no implementation."}

        try:
            result = self.execute_fn(**kwargs)
            if isinstance(result, dict):
                return result
            return {"success": True, "result": str(result)}
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            # Extract the last meaningful frame for concise context
            tb_lines = tb.strip().split("\n")
            short_tb = "\n".join(tb_lines[-4:]) if len(tb_lines) > 4 else tb
            return {
                "success": False,
                "result": f"Tool '{self.name}' crashed: {type(e).__name__}: {str(e)}",
                "error": short_tb,
                "error_type": type(e).__name__,
                "error_message": str(e),
            }

    def to_schema(self) -> Dict[str, Any]:
        """Convert to JSON schema for LLM consumption."""
        props = {}
        required = []
        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            props[param.name] = prop
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            }
        }

    def to_compact(self) -> str:
        """Compact one-line description for tight context."""
        params_str = ", ".join(
            f"{p.name}{'?' if not p.required else ''}: {p.type}"
            for p in self.parameters
        )
        return f"{self.name}({params_str}) — {self.description}"


class ToolRegistry:
    """Registry for all available tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())

    def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            tool_name: Tool name.
            **kwargs: Tool arguments.

        Returns:
            Execution result dict.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {
                "success": False,
                "result": f"Unknown tool: '{tool_name}'. Available: {', '.join(self._tools.keys())}"
            }
        return tool.execute(**kwargs)

    def format_for_llm(self, compact: bool = True) -> str:
        """
        Format all tools for LLM system prompt.

        Args:
            compact: If True, use compact format (saves tokens).

        Returns:
            Formatted tool descriptions string.
        """
        if compact:
            lines = ["## Available Tools"]
            # Group by category
            categories: Dict[str, List[Tool]] = {}
            for tool in self._tools.values():
                categories.setdefault(tool.category, []).append(tool)

            for cat, tools in sorted(categories.items()):
                lines.append(f"\n### {cat.title()}")
                for tool in tools:
                    lines.append(f"- {tool.to_compact()}")

            lines.append("\n## Tool Call Format")
            lines.append("Respond with a JSON block to call a tool:")
            lines.append('```json\n{"tool": "tool_name", "args": {"param": "value"}}\n```')
            lines.append("After each tool result, decide the next action or respond to the user.")

            return "\n".join(lines)
        else:
            schemas = [tool.to_schema() for tool in self._tools.values()]
            return json.dumps(schemas, indent=2)

    def parse_tool_call(self, response: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Parse a tool call from LLM response text.

        Looks for JSON blocks with 'tool' and 'args' keys.

        Args:
            response: LLM response text.

        Returns:
            Tuple of (tool_name, args_dict) or None if no tool call found.
        """
        # Try to find JSON in code block
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if "tool" in data:
                    return (data["tool"], data.get("args", {}))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object with tool key
        json_patterns = re.finditer(r'\{[^{}]*"tool"\s*:\s*"[^"]*"[^{}]*\}', response)
        for match in json_patterns:
            try:
                data = json.loads(match.group(0))
                if "tool" in data:
                    return (data["tool"], data.get("args", {}))
            except json.JSONDecodeError:
                continue

        # Try more permissive nested JSON
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
                    candidate = response[start:i+1]
                    try:
                        data = json.loads(candidate)
                        if "tool" in data:
                            return (data["tool"], data.get("args", {}))
                    except json.JSONDecodeError:
                        pass
                    start = None

        return None

    def parse_response_and_text(self, response: str) -> Tuple[Optional[Tuple[str, Dict]], str]:
        """
        Parse both tool call and accompanying text from response.

        Returns:
            Tuple of (tool_call_or_None, remaining_text).
        """
        tool_call = self.parse_tool_call(response)

        # Remove JSON blocks from text
        clean_text = re.sub(r'```(?:json)?\s*\{.*?\}\s*```', '', response, flags=re.DOTALL).strip()
        # Also remove bare JSON objects that look like tool calls
        clean_text = re.sub(r'\{[^{}]*"tool"\s*:\s*"[^"]*"[^{}]*\}', '', clean_text).strip()

        return (tool_call, clean_text)
