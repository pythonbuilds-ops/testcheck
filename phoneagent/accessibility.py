"""
Accessibility Parser — Parses Android UI hierarchy via uiautomator.

Provides structured access to the screen's UI elements, enabling
the agent to navigate via element text, IDs, and properties
instead of relying on vision.
"""

import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field


@dataclass
class UIElement:
    """Represents a single UI element from the accessibility tree."""

    index: int = 0
    text: str = ""
    resource_id: str = ""
    class_name: str = ""
    package: str = ""
    content_desc: str = ""
    checkable: bool = False
    checked: bool = False
    clickable: bool = False
    enabled: bool = True
    focusable: bool = False
    focused: bool = False
    scrollable: bool = False
    long_clickable: bool = False
    password: bool = False
    selected: bool = False
    bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    children: List["UIElement"] = field(default_factory=list)
    depth: int = 0

    @property
    def center(self) -> Tuple[int, int]:
        """Center coordinates of this element."""
        l, t, r, b = self.bounds
        return ((l + r) // 2, (t + b) // 2)

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    @property
    def display_text(self) -> str:
        """Best available text for display."""
        return self.text or self.content_desc or self.resource_id.split("/")[-1] if self.resource_id else ""

    def matches(
        self,
        text: Optional[str] = None,
        resource_id: Optional[str] = None,
        class_name: Optional[str] = None,
        content_desc: Optional[str] = None,
        clickable: Optional[bool] = None,
        scrollable: Optional[bool] = None,
    ) -> bool:
        """Check if this element matches the given criteria."""
        if text and text.lower() not in self.text.lower() and text.lower() not in self.content_desc.lower():
            return False
        if resource_id and resource_id.lower() not in self.resource_id.lower():
            return False
        if class_name and class_name.lower() not in self.class_name.lower():
            return False
        if content_desc and content_desc.lower() not in self.content_desc.lower():
            return False
        if clickable is not None and self.clickable != clickable:
            return False
        if scrollable is not None and self.scrollable != scrollable:
            return False
        return True

    def to_compact(self) -> str:
        """Compact single-line representation for LLM context."""
        parts = []
        # Short class name
        short_class = self.class_name.split(".")[-1] if self.class_name else ""
        parts.append(short_class)

        if self.text:
            parts.append(f'"{self.text}"')
        if self.content_desc and self.content_desc != self.text:
            parts.append(f'desc="{self.content_desc}"')
        if self.resource_id:
            short_id = self.resource_id.split("/")[-1]
            parts.append(f"id={short_id}")

        attrs = []
        if self.clickable:
            attrs.append("click")
        if self.scrollable:
            attrs.append("scroll")
        if self.checkable:
            chk = "☑" if self.checked else "☐"
            attrs.append(chk)
        if self.focused:
            attrs.append("focused")
        if not self.enabled:
            attrs.append("disabled")
        if attrs:
            parts.append(f"[{','.join(attrs)}]")

        cx, cy = self.center
        parts.append(f"@({cx},{cy})")

        return " ".join(parts)


class AccessibilityParser:
    """Parses and queries the Android UI accessibility tree."""

    def __init__(self, adb_controller):
        """
        Args:
            adb_controller: An ADBController instance.
        """
        self.adb = adb_controller

    def dump_and_parse(self) -> List[UIElement]:
        """
        Dump the UI tree from the device and parse it.

        Returns:
            Flat list of all UI elements.
        """
        xml_str = self.adb.dump_ui_xml()
        return self.parse_xml(xml_str)

    def parse_xml(self, xml_str: str) -> List[UIElement]:
        """
        Parse uiautomator XML dump into UIElement list.

        Args:
            xml_str: Raw XML string from uiautomator dump.

        Returns:
            Flat list of UIElement objects.
        """
        elements = []
        try:
            # Clean potential issues in XML
            xml_str = xml_str.strip()
            if not xml_str:
                return elements
            root = ET.fromstring(xml_str)
            self._parse_node(root, elements, depth=0)
        except ET.ParseError as e:
            # If XML is malformed, try to salvage what we can
            elements = self._fallback_parse(xml_str)
        return elements

    def _parse_bounds(self, bounds_str: str) -> Tuple[int, int, int, int]:
        """Parse bounds string '[x1,y1][x2,y2]' into tuple."""
        match = re.findall(r'\[(\d+),(\d+)\]', bounds_str)
        if len(match) == 2:
            return (
                int(match[0][0]), int(match[0][1]),
                int(match[1][0]), int(match[1][1])
            )
        return (0, 0, 0, 0)

    def _parse_node(
        self, node: ET.Element, elements: List[UIElement], depth: int
    ) -> Optional[UIElement]:
        """Recursively parse an XML node into UIElement."""
        attrib = node.attrib

        if attrib:  # Skip root hierarchy node if empty
            element = UIElement(
                index=int(attrib.get("index", 0)),
                text=attrib.get("text", ""),
                resource_id=attrib.get("resource-id", ""),
                class_name=attrib.get("class", ""),
                package=attrib.get("package", ""),
                content_desc=attrib.get("content-desc", ""),
                checkable=attrib.get("checkable", "false") == "true",
                checked=attrib.get("checked", "false") == "true",
                clickable=attrib.get("clickable", "false") == "true",
                enabled=attrib.get("enabled", "true") == "true",
                focusable=attrib.get("focusable", "false") == "true",
                focused=attrib.get("focused", "false") == "true",
                scrollable=attrib.get("scrollable", "false") == "true",
                long_clickable=attrib.get("long-clickable", "false") == "true",
                password=attrib.get("password", "false") == "true",
                selected=attrib.get("selected", "false") == "true",
                bounds=self._parse_bounds(attrib.get("bounds", "[0,0][0,0]")),
                depth=depth,
            )
            elements.append(element)

        for child in node:
            self._parse_node(child, elements, depth + 1)

    def _fallback_parse(self, xml_str: str) -> List[UIElement]:
        """
        Fallback regex-based parser for malformed XML.
        Extracts basic element info even if XML is broken.
        """
        elements = []
        # Find all node-like patterns
        pattern = r'<node\s+([^>]+?)/?>'
        for match in re.finditer(pattern, xml_str):
            attrs_str = match.group(1)

            def get_attr(name):
                m = re.search(rf'{name}="([^"]*)"', attrs_str)
                return m.group(1) if m else ""

            element = UIElement(
                text=get_attr("text"),
                resource_id=get_attr("resource-id"),
                class_name=get_attr("class"),
                content_desc=get_attr("content-desc"),
                clickable=get_attr("clickable") == "true",
                scrollable=get_attr("scrollable") == "true",
                enabled=get_attr("enabled") != "false",
                bounds=self._parse_bounds(get_attr("bounds")),
            )
            elements.append(element)

        return elements

    # ── Query Methods ───────────────────────────────────────────

    def find_elements(
        self,
        elements: List[UIElement],
        text: Optional[str] = None,
        resource_id: Optional[str] = None,
        class_name: Optional[str] = None,
        content_desc: Optional[str] = None,
        clickable: Optional[bool] = None,
        scrollable: Optional[bool] = None,
    ) -> List[UIElement]:
        """
        Find elements matching the given criteria.

        Args:
            elements: List of elements to search.
            text: Text to match (case-insensitive substring).
            resource_id: Resource ID to match.
            class_name: Class name to match.
            content_desc: Content description to match.
            clickable: Filter by clickable state.
            scrollable: Filter by scrollable state.

        Returns:
            Matching elements.
        """
        return [
            e for e in elements
            if e.matches(text, resource_id, class_name, content_desc, clickable, scrollable)
        ]

    def get_clickable_elements(self, elements: List[UIElement]) -> List[UIElement]:
        """Get all clickable/tappable elements."""
        return [e for e in elements if e.clickable and e.enabled]

    def get_text_elements(self, elements: List[UIElement]) -> List[UIElement]:
        """Get all elements that have visible text."""
        return [e for e in elements if e.text or e.content_desc]

    def get_scrollable_elements(self, elements: List[UIElement]) -> List[UIElement]:
        """Get all scrollable containers."""
        return [e for e in elements if e.scrollable]

    def get_input_fields(self, elements: List[UIElement]) -> List[UIElement]:
        """Get all text input fields."""
        return [
            e for e in elements
            if "EditText" in e.class_name or "edit" in e.resource_id.lower()
        ]

    # ── Screen Summary ──────────────────────────────────────────

    def build_screen_summary(
        self,
        elements: List[UIElement],
        max_tokens: int = 2000,
        include_all: bool = False,
    ) -> str:
        """
        Build a compact text summary of the current screen for LLM context.

        Prioritizes: interactive elements (clickable, input fields),
        visible text, and scrollable areas.

        Args:
            elements: Parsed UI elements.
            max_tokens: Approximate token budget.
            include_all: If True, include all elements (may exceed budget).

        Returns:
            Compact screen description.
        """
        if not elements:
            return "[Screen: No UI elements detected]"

        lines = []
        char_limit = int(max_tokens * 3.5)  # rough token-to-char

        # Header
        package = elements[0].package if elements else "unknown"
        lines.append(f"=== Screen: {package} ===")

        # Group elements by relevance
        interactive = []
        text_elements = []
        other = []

        for e in elements:
            if not e.display_text and not e.clickable and not e.scrollable:
                continue  # Skip empty non-interactive
            if e.clickable or e.scrollable or "EditText" in e.class_name:
                interactive.append(e)
            elif e.text or e.content_desc:
                text_elements.append(e)
            elif include_all:
                other.append(e)

        # Interactive elements (highest priority)
        if interactive:
            lines.append("\n--- Interactive Elements ---")
            for e in interactive:
                lines.append(f"  {e.to_compact()}")

        # Text content
        if text_elements:
            lines.append("\n--- Screen Text ---")
            seen_texts = set()
            for e in text_elements:
                txt = e.display_text
                if txt and txt not in seen_texts:
                    seen_texts.add(txt)
                    lines.append(f"  {e.to_compact()}")

        result = "\n".join(lines)

        # Enforce token limit
        if len(result) > char_limit:
            result = result[:char_limit] + "\n[...truncated]"

        return result

    def get_full_screen_text(self, elements: List[UIElement]) -> str:
        """Extract all readable text from screen elements."""
        texts = []
        seen = set()
        for e in elements:
            for txt in [e.text, e.content_desc]:
                if txt and txt not in seen:
                    seen.add(txt)
                    texts.append(txt)
        return "\n".join(texts)
