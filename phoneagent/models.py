"""
Model Manager — Multi-model routing via Groq API.

Routes requests to three specialized models:
- GPT-OSS-120b: Complex reasoning and planning
- Kimi K2: Fast execution and tool calling
- Llama 4 Scout: Vision / screen analysis
"""

import os
import time
import json
from typing import List, Dict, Any, Optional, Generator

from groq import Groq

from .token_manager import TokenManager


# ── Model Configs ───────────────────────────────────────────────

MODELS = {
    "reasoner": {
        "id": "openai/gpt-oss-120b",
        "name": "GPT-OSS-120b",
        "role": "Planning & Reasoning",
        "temperature": 1,
        "max_tokens": 8192,
        "top_p": 1,
        "reasoning_effort": "high",
        "supports_vision": False,
    },
    "executor": {
        "id": "moonshotai/kimi-k2-instruct-0905",
        "name": "Kimi K2",
        "role": "Execution & Tool Calling",
        "temperature": 0.6,
        "max_tokens": 4096,
        "top_p": 1,
        "reasoning_effort": None,
        "supports_vision": False,
    },
    "vision": {
        "id": "meta-llama/llama-4-scout-17b-16e-instruct",
        "name": "Llama 4 Scout",
        "role": "Vision & Screen Analysis",
        "temperature": 1,
        "max_tokens": 1024,
        "top_p": 1,
        "reasoning_effort": None,
        "supports_vision": True,
    },
}

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class ModelManager:
    """Routes requests to the appropriate Groq-hosted model."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize with Groq API key.

        Args:
            api_key: Groq API key. Falls back to GROQ_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GROQ_API_KEY not found. Set it as an environment variable or pass it directly."
            )
        self.client = Groq(api_key=self.api_key)
        self.token_manager = TokenManager()
        self._call_count = 0

    def _call_model(
        self,
        model_key: str,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        max_tokens_override: Optional[int] = None,
    ) -> str:
        """
        Internal method to call a model with retry logic.

        Args:
            model_key: One of 'reasoner', 'executor', 'vision'.
            messages: Chat messages.
            stream: Whether to stream the response.
            max_tokens_override: Override default max tokens.

        Returns:
            Complete response text.
        """
        config = MODELS[model_key]
        self._call_count += 1

        kwargs = {
            "model": config["id"],
            "messages": messages,
            "temperature": config["temperature"],
            "max_completion_tokens": max_tokens_override or config["max_tokens"],
            "top_p": config["top_p"],
            "stream": stream,
            "stop": None,
        }

        if config.get("reasoning_effort"):
            kwargs["reasoning_effort"] = config["reasoning_effort"]

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                if stream:
                    return self._handle_stream(kwargs)
                else:
                    completion = self.client.chat.completions.create(**kwargs)
                    return completion.choices[0].message.content or ""
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Rate limit — wait and retry
                if "rate" in error_str or "429" in error_str:
                    wait = RETRY_DELAY * (attempt + 1) * 2
                    time.sleep(wait)
                    continue

                # Token limit exceeded — reduce and retry
                if "token" in error_str or "context" in error_str:
                    # Trim messages more aggressively
                    if len(messages) > 2:
                        messages = [messages[0]] + messages[-2:]
                        kwargs["messages"] = messages
                        continue

                # Other transient errors
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue

                raise

        raise RuntimeError(f"Model {config['name']} failed after {MAX_RETRIES} retries: {last_error}")

    def _handle_stream(self, kwargs: Dict[str, Any]) -> str:
        """Handle streaming response, collecting all chunks."""
        chunks = []
        completion = self.client.chat.completions.create(**kwargs)
        for chunk in completion:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                chunks.append(delta.content)
        return "".join(chunks)

    # ── Public Interface ────────────────────────────────────────

    def reason(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        screen_data: Optional[str] = None,
        memory_context: Optional[str] = None,
    ) -> str:
        """
        Route to GPT-OSS-120b for complex reasoning / planning.

        Best for: task decomposition, error recovery, decision making,
        understanding complex user requests.

        Args:
            messages: Conversation messages (user/assistant).
            system: System prompt.
            screen_data: Current screen context.
            memory_context: Retrieved memory context.

        Returns:
            Model response text.
        """
        built = self.token_manager.build_request(
            system_prompt=system or "You are an intelligent phone control agent.",
            messages=messages,
            screen_data=screen_data,
            memory_context=memory_context,
        )
        return self._call_model("reasoner", built)

    def execute(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        screen_data: Optional[str] = None,
        memory_context: Optional[str] = None,
    ) -> str:
        """
        Route to Kimi K2 for fast execution / tool calling.

        Best for: selecting tools, generating action parameters,
        quick responses, general tasks.

        Args:
            messages: Conversation messages.
            system: System prompt.
            screen_data: Current screen context.
            memory_context: Retrieved memory context.

        Returns:
            Model response text.
        """
        built = self.token_manager.build_request(
            system_prompt=system or "You are an intelligent phone control agent.",
            messages=messages,
            screen_data=screen_data,
            memory_context=memory_context,
        )
        return self._call_model("executor", built)

    def see(
        self,
        image_base64: str,
        prompt: str,
        system: Optional[str] = None,
    ) -> str:
        """
        Route to Llama 4 Scout for vision / screen analysis.

        Best for: understanding screenshots, identifying UI elements,
        visual verification of action results.

        Args:
            image_base64: Base64-encoded JPEG image.
            prompt: Question or instruction about the image.
            system: Optional system prompt.

        Returns:
            Model response describing the image.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        })

        return self._call_model("vision", messages)

    def quick_query(self, prompt: str, model_key: str = "executor") -> str:
        """
        Quick one-shot query to any model.

        Args:
            prompt: User prompt.
            model_key: Model to use ('reasoner', 'executor', 'vision').

        Returns:
            Model response.
        """
        messages = [{"role": "user", "content": prompt}]
        return self._call_model(model_key, messages)

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            "total_calls": self._call_count,
        }
