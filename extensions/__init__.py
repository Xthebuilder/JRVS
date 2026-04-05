"""
JRVS Extensions — standalone modules that attach to JRVS without modifying core.

Available extensions:
  vision  — camera capture, local visual inference (LLaVA/Moondream), anomaly detection
  audio   — wake-word detection, Whisper STT, Piper/Kokoro TTS

Each extension exposes a single public class:
  from extensions.vision import VisionModule
  from extensions.audio import AudioModule
"""
from extensions.base import BaseExtension

__all__ = ["BaseExtension"]
