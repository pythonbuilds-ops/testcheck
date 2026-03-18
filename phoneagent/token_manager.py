"""
Token Manager — Handles the 10K token-per-request limit for Groq API.

Provides token counting, context compression, sliding window
management, and budget allocation across system prompt, context,
screen data, and response tokens.
"""

import re
from typing import List, Dict, Any, Optional


# ── Token Budget Constants ──────────────────────────────────────
MAX_TOKENS_PER_REQUEST = 10000
BUDGET_SYSTEM_PROMPT = 2000
BUDGET_CONTEXT = 4000
BUDGET_SCREEN_DATA = 2000
BUDGET_RESPONSE = 2000

# Rough chars-per-token ratio for estimation (conservative)
CHARS_PER_TOKEN = 3.5


class TokenManager:
    """Manages token budgets and context compression for the 10K limit."""

    def __init__(self, max_tokens: int = MAX_TOKENS_PER_REQUEST):
        self.max_tokens = max_tokens

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        Uses a character-ratio heuristic — fast and dependency-free.
        Roughly 1 token per 3.5 characters for English text.

        Args:
            text: Text to estimate tokens for.

        Returns:
            Estimated token count.
        """
        if not text:
            return 0
        return max(1, int(len(text) / CHARS_PER_TOKEN))

    def count_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """
        Estimate total tokens across a list of messages.

        Args:
            messages: List of message dicts with 'role' and 'content'.

        Returns:
            Estimated total token count.
        """
        total = 0
        for msg in messages:
            # Role overhead (~4 tokens)
            total += 4
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                # Multi-modal content
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            total += self.count_tokens(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            # Images consume ~1000 tokens approximately
                            total += 1000
        return total

    def trim_messages(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = BUDGET_CONTEXT,
        keep_first: int = 1,
        keep_last: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Trim message history to fit within token budget using sliding window.
        Keeps the first N and last M messages, summarizing the middle.

        Args:
            messages: Full message history.
            max_tokens: Maximum tokens for history.
            keep_first: Number of initial messages to always keep.
            keep_last: Number of recent messages to always keep.

        Returns:
            Trimmed message list.
        """
        if not messages:
            return []

        total = self.count_messages_tokens(messages)
        if total <= max_tokens:
            return messages

        if len(messages) <= keep_first + keep_last:
            return messages

        # Keep first N and last M, summarize middle
        first_msgs = messages[:keep_first]
        last_msgs = messages[-keep_last:]
        middle_msgs = messages[keep_first:-keep_last]

        # Create a compressed summary of middle messages
        middle_summary = self._summarize_messages(middle_msgs)
        summary_msg = {
            "role": "system",
            "content": f"[CONTEXT SUMMARY — {len(middle_msgs)} messages compressed]\n{middle_summary}"
        }

        result = first_msgs + [summary_msg] + last_msgs

        # If still too long, aggressively trim last messages
        while self.count_messages_tokens(result) > max_tokens and len(result) > 2:
            # Remove the oldest non-summary message after first
            if len(result) > 3:
                result.pop(2)
            else:
                break

        return result

    def _summarize_messages(self, messages: List[Dict[str, Any]]) -> str:
        """
        Create a compressed text summary of messages.
        This is a local extraction, not LLM-based, for speed.

        Args:
            messages: Messages to summarize.

        Returns:
            Compressed summary string.
        """
        summaries = []
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                content = " ".join(text_parts)

            # Truncate long content
            if len(content) > 200:
                content = content[:200] + "..."
            summaries.append(f"[{role}]: {content}")

        return "\n".join(summaries)

    def compress_text(self, text: str, max_tokens: int) -> str:
        """
        Compress text to fit within a token budget.

        Args:
            text: Text to compress.
            max_tokens: Maximum token budget.

        Returns:
            Compressed text.
        """
        current_tokens = self.count_tokens(text)
        if current_tokens <= max_tokens:
            return text

        # Calculate target character count
        target_chars = int(max_tokens * CHARS_PER_TOKEN)

        # Strategy 1: Remove excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        if len(text) <= target_chars:
            return text

        # Strategy 2: Truncate with ellipsis indicator
        # Keep first 70% and last 20% of target, skip middle
        first_cut = int(target_chars * 0.7)
        last_cut = int(target_chars * 0.2)

        compressed = text[:first_cut] + "\n\n[...content compressed...]\n\n" + text[-last_cut:]
        return compressed

    def build_request(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        screen_data: Optional[str] = None,
        memory_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build a token-budgeted request for the Groq API.

        Allocates tokens across:
        - System prompt: ~2000 tokens
        - Context/history: ~4000 tokens
        - Screen data: ~2000 tokens
        - Response budget: ~2000 tokens (reserved, not in messages)

        Args:
            system_prompt: System instruction.
            messages: Conversation history.
            screen_data: Current screen info (accessibility tree or description).
            memory_context: Retrieved memory context.

        Returns:
            Final messages list ready for API call.
        """
        # 1. Compress system prompt
        system_prompt = self.compress_text(system_prompt, BUDGET_SYSTEM_PROMPT)

        # 2. Build system message with optional memory and screen data
        system_parts = [system_prompt]

        if memory_context:
            compressed_memory = self.compress_text(memory_context, 800)
            system_parts.append(f"\n\n## Relevant Memories\n{compressed_memory}")

        if screen_data:
            compressed_screen = self.compress_text(screen_data, BUDGET_SCREEN_DATA)
            system_parts.append(f"\n\n## Current Screen\n{compressed_screen}")

        full_system = "\n".join(system_parts)

        # 3. Calculate remaining budget for messages
        system_tokens = self.count_tokens(full_system)
        remaining = self.max_tokens - system_tokens - BUDGET_RESPONSE
        remaining = max(remaining, 500)  # minimum message budget

        # 4. Trim message history
        trimmed = self.trim_messages(messages, max_tokens=remaining)

        # 5. Assemble final messages
        final_messages = [{"role": "system", "content": full_system}]
        final_messages.extend(trimmed)

        return final_messages

    def get_budget_report(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        screen_data: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Get a breakdown of token usage for debugging.

        Returns:
            Dict with token counts per component.
        """
        report = {
            "system_prompt": self.count_tokens(system_prompt),
            "messages": self.count_messages_tokens(messages),
            "screen_data": self.count_tokens(screen_data or ""),
            "max_budget": self.max_tokens,
            "response_reserved": BUDGET_RESPONSE,
        }
        report["total_used"] = report["system_prompt"] + report["messages"] + report["screen_data"]
        report["remaining_for_response"] = self.max_tokens - report["total_used"]
        return report
