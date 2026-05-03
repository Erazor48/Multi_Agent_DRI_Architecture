"""
TTS generation tool — synthesize speech via Google Cloud Text-to-Speech.

Authentication: uses GOOGLE_APPLICATION_CREDENTIALS (same service account as Vertex AI).
Prerequisite: "Cloud Text-to-Speech API" must be enabled in Google Cloud Console.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from dri.config.settings import settings
from dri.tools.base import BaseTool, ToolOutput, ToolRegistry


class TTSGenerateTool(BaseTool):
    name = "tts_generate"
    description = (
        "Generate speech audio from text using Google Cloud Text-to-Speech. "
        "Saves a WAV file to the specified workspace-relative path. "
        "Use this to create voice narrations for videos. "
        "Requires Cloud Text-to-Speech API enabled in Google Cloud Console."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to synthesize into speech.",
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Workspace-relative path for the output WAV file. "
                    "Example: 'shared/narration.wav' or '<dept>/_wip/voice.wav'."
                ),
            },
            "voice_name": {
                "type": "string",
                "description": (
                    "Google Cloud TTS voice name. "
                    "French Neural2: fr-FR-Neural2-A (female), fr-FR-Neural2-B (male). "
                    "French Studio (premium): fr-FR-Studio-A (female), fr-FR-Studio-D (male). "
                    "English Neural2: en-US-Neural2-F (female), en-US-Neural2-J (male). "
                    "Defaults to settings.google_tts_voice (fr-FR-Neural2-A)."
                ),
            },
            "speaking_rate": {
                "type": "number",
                "description": "Speaking rate between 0.25 and 4.0. Default: 1.0 (normal speed).",
                "default": 1.0,
                "minimum": 0.25,
                "maximum": 4.0,
            },
        },
        "required": ["text", "output_path"],
    }

    async def execute(self, raw_input: dict[str, Any]) -> ToolOutput:
        workspace_root: str = raw_input.get("_workspace_root", "")
        text: str = raw_input.get("text", "").strip()
        output_path_rel: str = raw_input.get("output_path", "").strip()
        voice_name: str = raw_input.get("voice_name", "") or settings.google_tts_voice
        speaking_rate: float = float(raw_input.get("speaking_rate", 1.0))

        if not text:
            return ToolOutput.fail("text is required.")
        if not output_path_rel:
            return ToolOutput.fail("output_path is required.")
        if not workspace_root:
            return ToolOutput.fail("tts_generate requires a persistent company workspace.")

        out_path = Path(workspace_root) / output_path_rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Derive language code from voice name (e.g. fr-FR-Neural2-A → fr-FR)
        language_code = "-".join(voice_name.split("-")[:2]) if voice_name else settings.google_tts_language

        def _synthesize() -> None:
            from google.cloud import texttospeech  # type: ignore[import-untyped]

            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name,
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,  # WAV
                speaking_rate=speaking_rate,
            )
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )
            out_path.write_bytes(response.audio_content)

        try:
            await asyncio.to_thread(_synthesize)
        except Exception as e:
            return ToolOutput.fail(
                f"TTS synthesis failed: {e}\n"
                "Check that 'Cloud Text-to-Speech API' is enabled in Google Cloud Console "
                "and that the service account has the 'Cloud Text-to-Speech User' role."
            )

        size_kb = out_path.stat().st_size // 1024
        return ToolOutput.ok({
            "path": output_path_rel,
            "size_kb": size_kb,
            "voice": voice_name,
            "message": f"Audio generated: {output_path_rel} ({size_kb} KB)",
        })


ToolRegistry.register(TTSGenerateTool())
