"""
ImageGenModule — queue-based image generation via a local ComfyUI instance.

Flow:
    1. Job queued via queue_job() (CLI, agent tool, or Slack)
    2. Workflow JSON assembled from _DEFAULT_WORKFLOW (or override file)
       with job params stamped in
    3. POST /prompt → ComfyUI job queue → poll /history until done
    4. GET /view → download PNG → save to ~/jarvis_sandbox/images/
    5. DB row updated (status=done, output_path, seed_used)
    6. Slack NOTIFY with output path

ComfyUI endpoint: http://127.0.0.1:8188 (override via COMFYUI_URL env var)

Default workflow uses UNETLoader + CLIPLoader(type="ovis") + VAELoader,
matching the installed OVIS diffusion model layout.
To override (e.g. for a different checkpoint or architecture) drop a
workflow JSON at:  ~/.jrvs/comfyui_workflow.json

The override file is loaded fresh on every job, so changes take effect
immediately without restarting the daemon.

Workflow override contract:
  - Must contain a node with class_type "KSampler" — stamped with seed/steps/cfg
  - Must contain a node with class_type "UNETLoader" — stamped with unet_name
  - Must contain a node with class_type "EmptyLatentImage" — stamped with width/height
  - Must contain a node with class_type "CLIPTextEncode" — positive prompt stamped in
  - Must contain a node with class_type "SaveImage" — filename_prefix stamped

If the override file does not follow this contract the module falls back to
the built-in default and logs a warning.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("jarvis.image_gen")

# ── Configuration ─────────────────────────────────────────────────────────────

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
COMFYUI_DEFAULT_MODEL = os.environ.get(
    "COMFYUI_DEFAULT_MODEL", "ovis_image_bf16.safetensors"
)
COMFYUI_DEFAULT_CLIP = os.environ.get(
    "COMFYUI_DEFAULT_CLIP", "ovis_2.5.safetensors"
)
COMFYUI_DEFAULT_VAE = os.environ.get(
    "COMFYUI_DEFAULT_VAE", "ae.safetensors"
)
COMFYUI_POLL_INTERVAL = int(os.environ.get("COMFYUI_POLL_INTERVAL", "2"))   # seconds
COMFYUI_POLL_TIMEOUT  = int(os.environ.get("COMFYUI_POLL_TIMEOUT",  "300")) # seconds

IMAGE_OUTPUT_DIR      = Path.home() / "jarvis_sandbox" / "images"
WORKFLOW_OVERRIDE_PATH = Path.home() / ".jrvs" / "comfyui_workflow.json"

# ── Default workflow (OVIS — UNETLoader + CLIPLoader + VAELoader) ─────────────
#
# Node map:
#   "1"  UNETLoader        — unet_name stamped per-job
#   "2"  CLIPLoader        — clip_name fixed; type="ovis"
#   "3"  VAELoader         — vae_name fixed
#   "4"  CLIPTextEncode    — positive prompt stamped per-job
#   "5"  CLIPTextEncode    — negative prompt (fixed default)
#   "6"  EmptyLatentImage  — width, height stamped per-job
#   "7"  KSampler          — seed, steps, cfg stamped per-job
#   "8"  VAEDecode
#   "9"  SaveImage         — filename_prefix stamped per-job

_DEFAULT_WORKFLOW: dict = {
    "1": {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "", "weight_dtype": "default"},
    },
    "2": {
        "class_type": "CLIPLoader",
        "inputs": {"clip_name": COMFYUI_DEFAULT_CLIP, "type": "ovis"},
    },
    "3": {
        "class_type": "VAELoader",
        "inputs": {"vae_name": COMFYUI_DEFAULT_VAE},
    },
    "4": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["2", 0]},
    },
    "5": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "ugly, blurry, low quality, watermark, text, cropped",
            "clip": ["2", 0],
        },
    },
    "6": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "7": {
        "class_type": "KSampler",
        "inputs": {
            "model":        ["1", 0],
            "positive":     ["4", 0],
            "negative":     ["5", 0],
            "latent_image": ["6", 0],
            "seed":         0,
            "steps":        20,
            "cfg":          7.0,
            "sampler_name": "euler",
            "scheduler":    "normal",
            "denoise":      1.0,
        },
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"images": ["8", 0], "filename_prefix": "jrvs_"},
    },
}


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ImageGenJob:
    prompt: str
    model:  str   = ""     # checkpoint filename; "" = COMFYUI_DEFAULT_MODEL
    steps:  int   = 20
    cfg:    float = 7.0
    width:  int   = 512
    height: int   = 512
    seed:   int   = -1     # -1 = random; resolved seed written back to DB
    source: str   = "manual"
    job_id: str   = field(default_factory=lambda: str(uuid.uuid4()))


# ── Module class ──────────────────────────────────────────────────────────────

class ImageGenModule:
    def __init__(self) -> None:
        self._queue:   asyncio.Queue[ImageGenJob] = asyncio.Queue()
        self._session: Optional[aiohttp.ClientSession] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Long-running queue consumer. Called by _supervise() in jarvis_daemon.py."""
        from core.database import db
        self._db = db

        IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        log.info(
            "ImageGenModule ready — ComfyUI at %s, output dir %s",
            COMFYUI_URL, IMAGE_OUTPUT_DIR,
        )

        # Own a single aiohttp session for the module's lifetime.
        # _supervise() restarts start() on crash, so the session is
        # always re-created cleanly.
        async with aiohttp.ClientSession() as session:
            self._session = session
            while True:
                try:
                    job = await self._queue.get()
                except asyncio.CancelledError:
                    raise
                try:
                    await self._process_job(job)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception(
                        "ImageGen job %s failed: %s", job.job_id[:8], exc
                    )
                    await self._fail_job(job, str(exc))
                finally:
                    self._queue.task_done()

    # ── Public API ────────────────────────────────────────────────────────

    async def queue_job(
        self,
        prompt: str,
        model:  str   = "",
        steps:  int   = 20,
        cfg:    float = 7.0,
        width:  int   = 512,
        height: int   = 512,
        seed:   int   = -1,
        source: str   = "manual",
    ) -> str:
        """Enqueue a generation job. Returns job_id."""
        if not prompt or not prompt.strip():
            raise ValueError("prompt cannot be empty")
        if steps < 1 or steps > 150:
            raise ValueError(f"steps must be 1-150, got {steps}")
        if cfg < 1.0 or cfg > 30.0:
            raise ValueError(f"cfg must be 1.0-30.0, got {cfg}")
        if width < 64 or height < 64 or width > 2048 or height > 2048:
            raise ValueError(f"size {width}x{height} out of range (64-2048)")

        job = ImageGenJob(
            prompt=prompt.strip(), model=model.strip(), steps=steps,
            cfg=cfg, width=width, height=height, seed=seed, source=source,
        )
        await self._db.upsert_image_job(job.job_id, {
            "prompt": job.prompt, "model": job.model or COMFYUI_DEFAULT_MODEL,
            "steps": job.steps, "cfg": job.cfg,
            "width": job.width, "height": job.height,
            "seed_used": -1, "status": "queued", "source": job.source,
        })
        await self._queue.put(job)
        log.info(
            "Queued image job %s: %r  %dx%d  steps=%d",
            job.job_id[:8], job.prompt[:60], job.width, job.height, job.steps,
        )
        return job.job_id

    async def list_jobs(
        self,
        status: Optional[str] = None,
        limit:  int = 10,
    ) -> list[dict]:
        """Return recent image jobs from the DB, newest first."""
        return await self._db.list_image_jobs(status=status, limit=limit)

    # ── Job processing ────────────────────────────────────────────────────

    async def _process_job(self, job: ImageGenJob) -> None:
        await self._db.upsert_image_job(job.job_id, {"status": "generating"})

        workflow, seed_used = _stamp_workflow(job)

        # Phase 1: submit to ComfyUI queue
        prompt_id = await self._submit(workflow)
        log.info("Job %s submitted to ComfyUI as prompt_id=%s", job.job_id[:8], prompt_id[:8])

        # Phase 2: poll until done
        image_info = await self._poll_until_done(prompt_id)

        # Phase 3: download PNG to local sandbox
        out_path = await self._download_image(image_info, job.job_id)
        log.info("Job %s done — saved to %s", job.job_id[:8], out_path)

        await self._db.upsert_image_job(job.job_id, {
            "status":      "done",
            "seed_used":   seed_used,
            "output_path": str(out_path),
        })
        await _notify_slack(
            f":frame_with_picture: *Image generated*\n"
            f"*Prompt:* {job.prompt[:200]}\n"
            f"*Model:* {job.model or COMFYUI_DEFAULT_MODEL}  "
            f"*Steps:* {job.steps}  *CFG:* {job.cfg}  "
            f"*Size:* {job.width}×{job.height}  *Seed:* {seed_used}\n"
            f"*Saved:* `{out_path}`"
        )

    async def _fail_job(self, job: ImageGenJob, error: str) -> None:
        """Mark a job failed and notify."""
        try:
            await self._db.upsert_image_job(job.job_id, {
                "status": "failed",
                "error":  error[:500],
            })
        except Exception as db_exc:
            log.error("Could not persist failure for job %s: %s", job.job_id[:8], db_exc)
        await _notify_slack(
            f":x: *Image generation failed*\n"
            f"*Job:* `{job.job_id[:8]}`  *Prompt:* {job.prompt[:120]}\n"
            f"```{error[:400]}```",
            channel_key="alerts",
        )

    # ── ComfyUI API calls ─────────────────────────────────────────────────

    async def _submit(self, workflow: dict) -> str:
        """POST the workflow to ComfyUI. Returns prompt_id."""
        payload = {
            "prompt":    workflow,
            "client_id": str(uuid.uuid4()),
        }
        try:
            async with self._session.post(
                f"{COMFYUI_URL}/prompt", json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                body = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(
                        f"ComfyUI /prompt returned HTTP {resp.status}: {body}"
                    )
                if body.get("node_errors"):
                    raise RuntimeError(
                        f"ComfyUI workflow node errors: {json.dumps(body['node_errors'])}"
                    )
                prompt_id = body.get("prompt_id")
                if not prompt_id:
                    raise RuntimeError(f"ComfyUI returned no prompt_id: {body}")
                return prompt_id
        except aiohttp.ClientConnectorError as exc:
            raise RuntimeError(
                f"Cannot connect to ComfyUI at {COMFYUI_URL}. "
                f"Is it running? Error: {exc}"
            ) from exc

    async def _poll_until_done(self, prompt_id: str) -> dict:
        """
        Poll GET /history/{prompt_id} until the job completes.
        Returns the first image info dict:
            {"filename": "...", "subfolder": "...", "type": "output"}
        Raises asyncio.TimeoutError if COMFYUI_POLL_TIMEOUT elapses.
        """
        deadline = time.monotonic() + COMFYUI_POLL_TIMEOUT
        url = f"{COMFYUI_URL}/history/{prompt_id}"

        while time.monotonic() < deadline:
            await asyncio.sleep(COMFYUI_POLL_INTERVAL)
            try:
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    history = await resp.json()
            except Exception as exc:
                log.warning("Poll error for %s: %s", prompt_id[:8], exc)
                continue

            if prompt_id not in history:
                continue  # queued but not started yet

            entry  = history[prompt_id]
            status = entry.get("status", {})

            if status.get("status_str") == "error":
                msgs = status.get("messages", [])
                raise RuntimeError(f"ComfyUI reported generation error: {msgs}")

            # Walk outputs to find the first saved image
            for node_output in entry.get("outputs", {}).values():
                images = node_output.get("images", [])
                if images:
                    return images[0]

            # outputs present but no images yet — still finishing
            if entry.get("outputs"):
                continue

        raise asyncio.TimeoutError(
            f"ComfyUI job {prompt_id[:8]} did not finish within "
            f"{COMFYUI_POLL_TIMEOUT}s"
        )

    async def _download_image(self, image_info: dict, job_id: str) -> Path:
        """GET /view and write the PNG to IMAGE_OUTPUT_DIR."""
        params = {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type":      image_info.get("type", "output"),
        }
        async with self._session.get(
            f"{COMFYUI_URL}/view", params=params,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"ComfyUI /view returned HTTP {resp.status} "
                    f"for {image_info['filename']}"
                )
            ext      = Path(image_info["filename"]).suffix or ".png"
            out_path = IMAGE_OUTPUT_DIR / f"{job_id[:8]}{ext}"
            out_path.write_bytes(await resp.read())
            return out_path


# ── Workflow helpers ──────────────────────────────────────────────────────────

def _load_workflow() -> dict:
    """Return the override workflow if it exists and is valid, else the default."""
    if WORKFLOW_OVERRIDE_PATH.exists():
        try:
            wf = json.loads(WORKFLOW_OVERRIDE_PATH.read_text())
            _validate_workflow(wf)
            log.debug("Using workflow override from %s", WORKFLOW_OVERRIDE_PATH)
            return wf
        except Exception as exc:
            log.warning(
                "Invalid workflow override at %s (%s) — using default",
                WORKFLOW_OVERRIDE_PATH, exc,
            )
    return copy.deepcopy(_DEFAULT_WORKFLOW)


def _validate_workflow(wf: dict) -> None:
    """Raise ValueError if required node types are missing."""
    types = {node["class_type"] for node in wf.values() if isinstance(node, dict)}
    required = {"KSampler", "EmptyLatentImage", "SaveImage"}
    # Accept either split loaders (UNETLoader) or single checkpoint (CheckpointLoaderSimple)
    if "UNETLoader" not in types and "CheckpointLoaderSimple" not in types:
        required.add("CheckpointLoaderSimple")  # will trigger missing message
    missing = required - types
    if missing:
        raise ValueError(f"Workflow missing required node types: {missing}")


def _stamp_workflow(job: ImageGenJob) -> tuple[dict, int]:
    """
    Deep-copy the workflow and stamp in per-job values.
    Returns (stamped_workflow, resolved_seed).
    """
    wf = _load_workflow()
    seed = job.seed if job.seed >= 0 else random.randint(0, 2**32 - 1)
    model = job.model or COMFYUI_DEFAULT_MODEL
    prefix = f"jrvs_{job.job_id[:8]}_"

    for node in wf.values():
        if not isinstance(node, dict):
            continue
        ct     = node.get("class_type", "")
        inputs = node.get("inputs", {})

        if ct == "KSampler":
            inputs.update({"seed": seed, "steps": job.steps, "cfg": job.cfg})

        elif ct == "UNETLoader":
            inputs["unet_name"] = model

        elif ct == "CheckpointLoaderSimple":
            inputs["ckpt_name"] = model

        elif ct == "EmptyLatentImage":
            inputs.update({"width": job.width, "height": job.height})

        elif ct == "CLIPTextEncode":
            # Only stamp the positive prompt — identified by its clip source
            # coming from the checkpoint node (not another CLIP node).
            clip_src = inputs.get("clip")
            if isinstance(clip_src, list) and len(clip_src) == 2:
                # Positive prompt node: clip comes from CheckpointLoaderSimple
                # output 1, which is the standard SD graph connection.
                # We stamp whichever CLIPTextEncode node has an empty or
                # placeholder text (i.e. the one we own in the default workflow).
                # In override workflows: stamp the first CLIPTextEncode that
                # does NOT look like a negative prompt node.
                existing = inputs.get("text", "")
                if not existing or existing == job.prompt or (
                    "ugly" not in existing and "blurry" not in existing
                ):
                    inputs["text"] = job.prompt

        elif ct == "SaveImage":
            inputs["filename_prefix"] = prefix

    return wf, seed


# ── Slack helper ──────────────────────────────────────────────────────────────

async def _notify_slack(text: str, channel_key: Optional[str] = None) -> None:
    try:
        from core.slack_notifier import notify_async
        await notify_async(text, channel_key=channel_key)
    except Exception as exc:
        log.debug("_notify_slack: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
image_gen_module = ImageGenModule()
