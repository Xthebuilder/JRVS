"""
Vision extension configuration.

Loads extensions/vision/config.yaml then applies environment-variable overrides.
Environment variables use the prefix JRVS_VISION_, e.g.:
  JRVS_VISION_CAMERA_SOURCE=http://192.168.1.50:4747/video
  JRVS_VISION_INFERENCE_BACKEND=moondream
  JRVS_VISION_ENABLED=false
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

_CONFIG_FILE = Path(__file__).parent / "config.yaml"


def _load_yaml() -> Dict[str, Any]:
    with open(_CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def _env(key: str, default: Any) -> Any:
    """Read JRVS_VISION_<KEY> from environment, coercing type to match default."""
    env_key = f"JRVS_VISION_{key.upper()}"
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


def _parse_camera_source(raw: Any) -> Union[int, str]:
    """Return int for device index, str for URL."""
    if isinstance(raw, int):
        return raw
    try:
        return int(raw)
    except (TypeError, ValueError):
        return str(raw)


class VisionConfig:
    """Flat-ish config object for the vision extension."""

    def __init__(self) -> None:
        data = _load_yaml()

        # ── top level ──────────────────────────────────────────────────────────
        self.enabled: bool = _env("enabled", data.get("enabled", True))

        # ── camera ────────────────────────────────────────────────────────────
        cam = data.get("camera", {})
        raw_source = _env("camera_source", cam.get("source", 0))
        self.camera_source: Union[int, str] = _parse_camera_source(raw_source)
        self.fps_capture: float = _env("camera_fps_capture", cam.get("fps_capture", 2))
        self.motion_threshold: float = _env(
            "camera_motion_threshold", cam.get("motion_threshold", 0.05)
        )
        self.periodic_interval: float = _env(
            "camera_periodic_interval", cam.get("periodic_interval", 30)
        )
        self.max_width: int = _env("camera_max_width", cam.get("max_width", 512))

        # ── inference ─────────────────────────────────────────────────────────
        inf = data.get("inference", {})
        self.inference_backend: str = _env(
            "inference_backend", inf.get("backend", "llava")
        )
        self.inference_prompt: str = inf.get(
            "prompt",
            "Briefly describe what you see. Focus on people, objects, and activities.",
        )

        llava = inf.get("llava", {})
        self.llava_model: str = _env("llava_model", llava.get("model", "llava:7b"))
        self.llava_ollama_url: str = _env(
            "llava_ollama_url",
            llava.get("ollama_url", os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")),
        )
        self.llava_timeout: int = _env("llava_timeout", llava.get("timeout", 60))

        moon = inf.get("moondream", {})
        self.moondream_model_id: str = _env(
            "moondream_model_id", moon.get("model_id", "vikhyatk/moondream2")
        )
        self.moondream_revision: str = _env(
            "moondream_revision", moon.get("revision", "2025-01-09")
        )
        self.moondream_model_path: Optional[str] = _env(
            "moondream_model_path", moon.get("model_path")
        )

        # ── memory ────────────────────────────────────────────────────────────
        mem = data.get("memory", {})
        self.db_path: Optional[str] = _env("db_path", mem.get("db_path"))
        self.log_level: str = _env("log_level", mem.get("log_level", "scene"))

        # ── anomaly ───────────────────────────────────────────────────────────
        ano = data.get("anomaly", {})
        self.anomaly_enabled: bool = _env("anomaly_enabled", ano.get("enabled", True))
        self.anomaly_window_size: int = _env(
            "anomaly_window_size", ano.get("window_size", 100)
        )
        self.anomaly_similarity_threshold: float = _env(
            "anomaly_similarity_threshold", ano.get("similarity_threshold", 0.70)
        )
        self.anomaly_alert_threshold: float = _env(
            "anomaly_alert_threshold", ano.get("alert_threshold", 0.85)
        )

        # ── alerts ────────────────────────────────────────────────────────────
        ale = data.get("alerts", {})
        self.alerts_queue_size: int = _env(
            "alerts_queue_size", ale.get("queue_size", 50)
        )
        self.alerts_write_to_jrvs_events: bool = _env(
            "alerts_write_to_jrvs_events", ale.get("write_to_jrvs_events", True)
        )
        self.alerts_min_severity: str = _env(
            "alerts_min_severity", ale.get("min_severity", "medium")
        )

        self._validate()

    def _validate(self) -> None:
        if self.fps_capture <= 0:
            raise ValueError("camera.fps_capture must be > 0")
        if not (0.0 <= self.motion_threshold <= 1.0):
            raise ValueError("camera.motion_threshold must be in [0, 1]")
        if self.inference_backend not in ("llava", "moondream"):
            raise ValueError("inference.backend must be 'llava' or 'moondream'")
        if self.log_level not in ("all", "scene", "anomaly"):
            raise ValueError("memory.log_level must be 'all', 'scene', or 'anomaly'")
        if self.alerts_min_severity not in ("low", "medium", "high"):
            raise ValueError("alerts.min_severity must be 'low', 'medium', or 'high'")


# Module-level singleton — import this everywhere inside the vision extension
vision_config = VisionConfig()
