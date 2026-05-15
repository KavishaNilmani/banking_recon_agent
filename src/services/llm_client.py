"""
LLM Client — auto-detects Anthropic or Azure OpenAI based on environment variables.

Selection logic:
  Azure OpenAI  — when AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT are all set
  Anthropic     — otherwise (requires ANTHROPIC_API_KEY)
"""

import json
import os
from dataclasses import dataclass, field


@dataclass
class NormalizedBlock:
    """Unified content block from either provider."""
    type: str           # "text" or "tool_use"
    text: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)
    id: str = ""


class NormalizedResponse:
    """Unified API response — same interface regardless of provider."""

    def __init__(self, stop_reason: str, content: list, raw_content: list):
        self.stop_reason = stop_reason
        self.content = content
        # Anthropic-format dicts — stored in message history for both providers
        self._raw_content = raw_content


def detect_provider() -> str:
    azure_vars = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")
    if all(os.environ.get(v) for v in azure_vars):
        return "azure_openai"
    return "anthropic"


class LLMClient:

    def __init__(self):
        self.provider = detect_provider()

        if self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            self.model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        else:  # azure_openai
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            )
            self.model = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    # ------------------------------------------------------------------
    def create_message(
        self,
        system: str,
        tools: list,
        messages: list,
        max_tokens: int = 4096,
    ) -> NormalizedResponse:
        # Ensure message history fits within provider context limits before calling.
        if self.provider == "azure_openai":
            # Azure/OpenAI models provide a large context; allow override via env var.
            try:
                provider_context = int(os.environ.get("AZURE_MAX_CONTEXT_TOKENS", "128000"))
            except Exception:
                provider_context = 128000

            # Reserve space for the completion itself and a small safety margin.
            safety_margin = int(os.environ.get("AZURE_CONTEXT_SAFETY_MARGIN_TOKENS", "1000"))
            allowed_message_tokens = max(0, provider_context - max_tokens - safety_margin)

            messages = self._trim_messages_to_token_limit(messages, allowed_message_tokens)

            return self._call_azure(system, tools, messages, max_tokens)

        # Anthropic/default path: allow override via env var for safety, otherwise call directly.
        try:
            anthropic_context = int(os.environ.get("ANTHROPIC_MAX_CONTEXT_TOKENS", "131072"))
        except Exception:
            anthropic_context = 131072
        safety_margin = int(os.environ.get("ANTHROPIC_CONTEXT_SAFETY_MARGIN_TOKENS", "1000"))
        allowed_message_tokens = max(0, anthropic_context - max_tokens - safety_margin)
        messages = self._trim_messages_to_token_limit(messages, allowed_message_tokens)
        return self._call_anthropic(system, tools, messages, max_tokens)

    # ------------------------------------------------------------------
    def _call_anthropic(self, system, tools, messages, max_tokens) -> NormalizedResponse:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )

        blocks = []
        raw = []

        for block in response.content:
            if block.type == "text":
                blocks.append(NormalizedBlock(type="text", text=block.text))
                raw.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                blocks.append(NormalizedBlock(
                    type="tool_use", name=block.name, input=block.input, id=block.id,
                ))
                raw.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})

        return NormalizedResponse(
            stop_reason=response.stop_reason,
            content=blocks,
            raw_content=raw,
        )

    # ------------------------------------------------------------------
    def _call_azure(self, system, tools, messages, max_tokens) -> NormalizedResponse:
        oai_messages = self._to_openai_messages(system, messages)
        oai_tools = self._to_openai_tools(tools)

        # Respect model/provider maximums. Allow override via env var `AZURE_MAX_COMPLETION_TOKENS`.
        try:
            provider_max = int(os.environ.get("AZURE_MAX_COMPLETION_TOKENS", "4096"))
        except Exception:
            provider_max = 4096

        allowed_max = max(1, min(max_tokens, provider_max))

        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=allowed_max,
            messages=oai_messages,
            tools=oai_tools,
            tool_choice="auto",
        )

        choice = response.choices[0]
        msg = choice.message

        blocks = []
        raw = []

        if msg.content:
            blocks.append(NormalizedBlock(type="text", text=msg.content))
            raw.append({"type": "text", "text": msg.content})

        for tc in msg.tool_calls or []:
            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            blocks.append(NormalizedBlock(
                type="tool_use", name=tc.function.name, input=args, id=tc.id,
            ))
            raw.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": args})

        stop_reason = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"

        return NormalizedResponse(stop_reason=stop_reason, content=blocks, raw_content=raw)

    # ------------------------------------------------------------------
    @staticmethod
    def _to_openai_tools(tools: list) -> list:
        """Convert Anthropic tool schema to OpenAI function schema."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    @staticmethod
    def _to_openai_messages(system: str, messages: list) -> list:
        """Convert Anthropic-format message history to OpenAI chat format."""
        out = [{"role": "system", "content": system}]

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                if isinstance(content, str):
                    out.append({"role": "user", "content": content})
                else:
                    # List content — may contain tool_result blocks
                    tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                    if tool_results:
                        for tr in tool_results:
                            out.append({
                                "role": "tool",
                                "tool_call_id": tr["tool_use_id"],
                                "content": tr["content"],
                            })
                    else:
                        text = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
                        out.append({"role": "user", "content": text})

            elif role == "assistant":
                if isinstance(content, str):
                    out.append({"role": "assistant", "content": content})
                else:
                    text_parts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    tool_calls = [
                        {
                            "id": b["id"],
                            "type": "function",
                            "function": {
                                "name": b["name"],
                                "arguments": json.dumps(b["input"]),
                            },
                        }
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "tool_use"
                    ]
                    assistant_msg = {"role": "assistant", "content": " ".join(text_parts) or None}
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                    out.append(assistant_msg)

        return out

    # ------------------------------------------------------------------
    def _estimate_tokens_for_message(self, msg: dict) -> int:
        """Rudimentary token estimate: use character count heuristic.

        This is conservative and intended to provide a quick way to trim history
        without pulling in tiktoken as a dependency.
        """
        content = msg.get("content", "")
        if isinstance(content, (list, dict)):
            content_str = json.dumps(content, ensure_ascii=False)
        else:
            content_str = str(content or "")

        role = str(msg.get("role", ""))
        # estimate: ~4 characters per token (heuristic)
        chars = len(role) + 1 + len(content_str)
        return max(1, int(chars / 4))

    def _trim_messages_to_token_limit(self, messages: list, allowed_tokens: int) -> list:
        """Trim oldest non-system messages until estimated tokens <= allowed_tokens.

        Preserves all `system` role messages and removes oldest `user`/`assistant`
        entries first. If allowed_tokens <= 0, keep only system messages.
        """
        if allowed_tokens <= 0:
            return [m for m in messages if m.get("role") == "system"]

        # Quick path: estimate total tokens
        total = sum(self._estimate_tokens_for_message(m) for m in messages)
        if total <= allowed_tokens:
            return messages

        # Keep system messages, trim from the start of the non-system list
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        while other_msgs and total > allowed_tokens:
            removed = other_msgs.pop(0)
            total -= self._estimate_tokens_for_message(removed)

        # Enforce hard cap on number of non-system messages to avoid under-estimation
        try:
            max_msgs = int(os.environ.get("LLM_HISTORY_MAX_MESSAGES", "40"))
        except Exception:
            max_msgs = 40

        if len(other_msgs) > max_msgs:
            # drop oldest to keep the last `max_msgs`
            drop_count = len(other_msgs) - max_msgs
            for _ in range(drop_count):
                removed = other_msgs.pop(0)
                total -= self._estimate_tokens_for_message(removed)

        trimmed = system_msgs + other_msgs

        if len(messages) != len(trimmed):
            print(f"[llm_client] Trimmed message history: kept {len(trimmed)} of {len(messages)} messages")

        # If still over the limit (rare), truncate the last message's content string
        if total > allowed_tokens and trimmed:
            # find the last non-system message to truncate
            for i in range(len(trimmed) - 1, -1, -1):
                if trimmed[i].get("role") != "system":
                    content = trimmed[i].get("content")
                    if isinstance(content, str) and content:
                        # compute allowed chars approximation
                        allowed_chars = max(20, (allowed_tokens - (total - self._estimate_tokens_for_message(trimmed[i]))) * 4)
                        trimmed[i]["content"] = content[:allowed_chars]
                    else:
                        trimmed.pop(i)
                    break

        return [m for m in trimmed if m is not None]
