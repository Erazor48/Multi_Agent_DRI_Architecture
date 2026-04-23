"""
Google Gemini provider (google-genai SDK >= 1.10).
Converts our wire format ↔ Gemini SDK format.
"""
from __future__ import annotations

import json
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from dri.llm.base import BaseLLMProvider, LLMResponse, ToolCall


class GeminiProvider(BaseLLMProvider):
    def __init__(
        self,
        *,
        api_key: str = "",
        vertex_ai: bool = False,
        project: str = "",
        location: str = "us-central1",
        credentials_file: str = "",
    ) -> None:
        from google import genai

        if vertex_ai:
            import os
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                credentials_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            # Extract project from credentials file if not explicitly provided
            resolved_project = project or creds.service_account_email.split("@")[1].split(".")[0]
            if not project:
                import json
                with open(credentials_file) as f:
                    resolved_project = json.load(f).get("project_id", "")

            self._client = genai.Client(
                vertexai=True,
                project=resolved_project,
                location=location,
                credentials=creds,
            )
        else:
            self._client = genai.Client(api_key=api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
    async def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
    ) -> LLMResponse:
        from google.genai import types

        contents = self._to_gemini_contents(messages)

        config_kwargs: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": max_tokens,
        }
        if tools:
            config_kwargs["tools"] = [self._to_gemini_tools(tools)]

        response = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return self._to_llm_response(response)

    # ── Wire format → Gemini ──────────────────────────────────────────────

    @staticmethod
    def _to_gemini_contents(messages: list[dict[str, Any]]) -> list[Any]:
        from google.genai import types

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]

            if isinstance(content, str):
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content)],
                ))
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if block.get("type") == "text":
                        parts.append(types.Part.from_text(text=block["text"]))
                    elif block.get("type") == "tool_use":
                        parts.append(types.Part.from_function_call(
                            name=block["name"],
                            args=block.get("input", {}),
                        ))
                    elif block.get("type") == "tool_result":
                        # Tool results must be in a user-role content with function_response
                        result_content = block.get("content", "")
                        # Try to parse JSON, fall back to string
                        try:
                            result_data = json.loads(result_content) if isinstance(result_content, str) else result_content
                        except (json.JSONDecodeError, TypeError):
                            result_data = {"result": str(result_content)}
                        parts.append(types.Part.from_function_response(
                            name=block.get("tool_use_id", "unknown"),
                            response=result_data,
                        ))
                if parts:
                    contents.append(types.Content(role=role, parts=parts))

        return contents

    @staticmethod
    def _to_gemini_tools(tools: list[dict[str, Any]]) -> Any:
        """Convert Anthropic-style tool specs to a Gemini Tool object."""
        from google.genai import types

        declarations = []
        for tool in tools:
            schema = tool.get("input_schema", {})
            declarations.append(types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=_json_schema_to_gemini_schema(schema),
            ))
        return types.Tool(function_declarations=declarations)

    # ── Gemini → LLMResponse ──────────────────────────────────────────────

    @staticmethod
    def _to_llm_response(response: Any) -> LLMResponse:
        text = ""
        tool_calls: list[ToolCall] = []
        input_tokens = 0
        output_tokens = 0

        if response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0

        if not response.candidates:
            return LLMResponse(text="", input_tokens=input_tokens, output_tokens=output_tokens)

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            return LLMResponse(text="", input_tokens=input_tokens, output_tokens=output_tokens)

        for part in candidate.content.parts:
            if part.text:
                text += part.text
            elif part.function_call:
                import uuid
                tool_calls.append(ToolCall(
                    id=str(uuid.uuid4()),
                    name=part.function_call.name,
                    input=dict(part.function_call.args) if part.function_call.args else {},
                ))

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )


# ── JSON Schema → Gemini Schema ───────────────────────────────────────────────

def _json_schema_to_gemini_schema(schema: dict[str, Any]) -> Any:
    """Recursively convert a JSON Schema dict to a google.genai.types.Schema."""
    from google.genai import types

    json_type = schema.get("type", "string").upper()
    gemini_type = getattr(types.Type, json_type, types.Type.STRING)

    kwargs: dict[str, Any] = {"type": gemini_type}

    if "description" in schema:
        kwargs["description"] = schema["description"]

    if "enum" in schema:
        kwargs["enum"] = [str(e) for e in schema["enum"]]

    if json_type == "OBJECT" and "properties" in schema:
        kwargs["properties"] = {
            k: _json_schema_to_gemini_schema(v)
            for k, v in schema["properties"].items()
        }
        if "required" in schema:
            kwargs["required"] = schema["required"]

    if json_type == "ARRAY" and "items" in schema:
        kwargs["items"] = _json_schema_to_gemini_schema(schema["items"])

    return types.Schema(**kwargs)
