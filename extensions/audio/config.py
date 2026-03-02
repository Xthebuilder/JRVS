"""
Audio extension configuration.

Loads extensions/audio/config.yaml then applies environment-variable overrides.
Environment variables use the prefix JRVS_AUDIO_, e.g.:
  JRVS_AUDIO_INPUT_DEVICE=USB Microphone
  JRVS_AUDIO_STT_MODEL=small
  JRVS_AUDIO_TTS_BACKEND=kokoro
  JRVS_AUDIO_CONVERSATION_WAKE_WORD=hey jarvis
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Union

import yaml

_CONFIG_FILE = Path(__file__).parent / "config.yaml"


def _load_yaml():
    with open(_CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def _env(key: str, default: Any) -> Any:
    env_key = f"JRVS_AUDIO_{key.upper()}"
    raw = os.environ.get(env_key)
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


class AudioConfig:
    """Flat-ish config object for the audio extension."""

    def __init__(self) -> None:
        data = _load_yaml()

        self.enabled: bool = _env("enabled", data.get("enabled", True))

        # ── input ─────────────────────────────────────────────────────────────
        inp = data.get("input", {})
        raw_device = _env("input_device", inp.get("device"))
        self.input_device: Optional[Union[int, str]] = (
            None if raw_device in (None, "null", "")
            else (int(raw_device) if str(raw_device).isdigit() else raw_device)
        )
        self.sample_rate: int = _env("input_sample_rate", inp.get("sample_rate", 16000))
        self.channels: int = _env("input_channels", inp.get("channels", 1))
        self.chunk_ms: int = _env("input_chunk_ms", inp.get("chunk_ms", 30))
        self.vad_aggressiveness: int = _env(
            "input_vad_aggressiveness", inp.get("vad_aggressiveness", 2)
        )
        self.silence_timeout: float = _env(
            "input_silence_timeout", inp.get("silence_timeout", 1.5)
        )
        self.max_duration: float = _env(
            "input_max_duration", inp.get("max_duration", 30)
        )

        # ── STT ───────────────────────────────────────────────────────────────
        stt = data.get("stt", {})
        self.stt_backend: str = _env("stt_backend", stt.get("backend", "whisper"))
        self.whisper_model: str = _env("stt_model", stt.get("model", "base"))
        self.whisper_language: Optional[str] = _env(
            "stt_language", stt.get("language", "en") or None
        )
        self.whisper_device: str = _env("stt_device", stt.get("device", "cpu"))
        self.whisper_compute_type: str = _env(
            "stt_compute_type", stt.get("compute_type", "int8")
        )

        # ── TTS ───────────────────────────────────────────────────────────────
        tts = data.get("tts", {})
        self.tts_backend: str = _env("tts_backend", tts.get("backend", "piper"))
        self.tts_speed: float = _env("tts_speed", tts.get("speed", 1.0))

        piper = tts.get("piper", {})
        self.piper_model: str = _env(
            "tts_piper_model", piper.get("model", "en_US-lessac-medium")
        )
        self.piper_models_dir: str = _env(
            "tts_piper_models_dir",
            str(Path(piper.get("models_dir", "~/.local/share/piper-voices")).expanduser()),
        )
        self.piper_binary: str = _env("tts_piper_binary", piper.get("binary", "piper"))
        self.piper_sample_rate: int = _env(
            "tts_piper_sample_rate", piper.get("output_sample_rate", 22050)
        )

        kokoro = tts.get("kokoro", {})
        raw_kokoro_path = kokoro.get("model_path")
        self.kokoro_model_path: Optional[str] = (
            None if raw_kokoro_path in (None, "null", "")
            else str(Path(raw_kokoro_path).expanduser())
        )
        self.kokoro_voice: str = _env("tts_kokoro_voice", kokoro.get("voice", "af_sky"))
        self.kokoro_lang_code: str = _env(
            "tts_kokoro_lang_code", kokoro.get("lang_code", "a")
        )

        # ── conversation ──────────────────────────────────────────────────────
        conv = data.get("conversation", {})
        raw_ww = _env("conversation_wake_word", conv.get("wake_word", "hey jarvis"))
        self.wake_word: Optional[str] = (
            None if raw_ww in (None, "null", "") else str(raw_ww)
        )
        self.wake_word_threshold: float = _env(
            "conversation_wake_word_threshold",
            conv.get("wake_word_threshold", 0.5),
        )
        self.ack_tone: bool = _env("conversation_ack_tone", conv.get("ack_tone", True))
        self.response_prefix: str = _env(
            "conversation_response_prefix", conv.get("response_prefix", "")
        )

        # ── command mode ──────────────────────────────────────────────────────
        cmd = data.get("command_mode", {})
        self.cmd_enabled: bool = _env("command_mode_enabled", cmd.get("enabled", True))
        self.cmd_trigger: str = _env(
            "command_mode_trigger", cmd.get("trigger", "command mode")
        )
        self.cmd_multi_command: bool = _env(
            "command_mode_multi_command", cmd.get("multi_command", True)
        )
        self.cmd_timeout: float = _env(
            "command_mode_timeout", cmd.get("timeout", 10.0)
        )

        self._validate()

    def _validate(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("input.sample_rate must be > 0")
        if self.chunk_ms not in (10, 20, 30):
            raise ValueError("input.chunk_ms must be 10, 20, or 30 (webrtcvad requirement)")
        if self.vad_aggressiveness not in (0, 1, 2, 3):
            raise ValueError("input.vad_aggressiveness must be 0–3")
        if self.tts_backend not in ("piper", "kokoro"):
            raise ValueError("tts.backend must be 'piper' or 'kokoro'")
        if self.stt_backend != "whisper":
            raise ValueError("stt.backend must be 'whisper' (only STT backend supported)")
        if self.whisper_model not in ("tiny", "base", "small", "medium", "large-v3", "large"):
            raise ValueError(
                "stt.model must be one of: tiny, base, small, medium, large-v3, large"
            )


# Module-level singleton
audio_config = AudioConfig()
