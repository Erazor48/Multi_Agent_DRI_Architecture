"""Unit tests for tts_generate tool — mocks Google Cloud TTS client."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_tts_missing_text():
    from dri.tools.tts_generate import TTSGenerateTool
    tool = TTSGenerateTool()
    result = await tool.execute({"_workspace_root": "/tmp", "output_path": "shared/out.wav"})
    assert not result.success
    assert "text" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_tts_missing_output_path():
    from dri.tools.tts_generate import TTSGenerateTool
    tool = TTSGenerateTool()
    result = await tool.execute({"_workspace_root": "/tmp", "text": "Hello"})
    assert not result.success
    assert "output_path" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_tts_no_workspace():
    from dri.tools.tts_generate import TTSGenerateTool
    tool = TTSGenerateTool()
    result = await tool.execute({"text": "Hello", "output_path": "shared/out.wav"})
    assert not result.success
    assert "workspace" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_tts_success(tmp_path):
    from dri.tools.tts_generate import TTSGenerateTool
    tool = TTSGenerateTool()

    fake_audio = b"RIFF" + b"\x00" * 100  # fake WAV bytes

    mock_response = MagicMock()
    mock_response.audio_content = fake_audio

    with patch("google.cloud.texttospeech.TextToSpeechClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.synthesize_speech.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = await tool.execute({
            "_workspace_root": str(tmp_path),
            "text": "Bonjour le monde",
            "output_path": "shared/test.wav",
            "voice_name": "fr-FR-Neural2-A",
        })

    assert result.success
    out_file = tmp_path / "shared" / "test.wav"
    assert out_file.exists()
    assert out_file.read_bytes() == fake_audio


@pytest.mark.asyncio
async def test_tts_api_error(tmp_path):
    from dri.tools.tts_generate import TTSGenerateTool
    tool = TTSGenerateTool()

    with patch("google.cloud.texttospeech.TextToSpeechClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.synthesize_speech.side_effect = Exception("API quota exceeded")
        mock_client_cls.return_value = mock_client

        result = await tool.execute({
            "_workspace_root": str(tmp_path),
            "text": "Test",
            "output_path": "shared/test.wav",
        })

    assert not result.success
    assert "TTS synthesis failed" in (result.error or "")
