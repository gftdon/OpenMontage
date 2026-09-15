"""Higgsfield video generation via the Higgsfield CLI (`higgsfield` / `hf`).

The CLI is OAuth-authenticated (see `higgsfield auth login`) and routes to the
same backend as the web app — Seedance, Kling, Veo, Grok, MiniMax and friends —
billed in credits against the selected workspace. This tool shells out to the
CLI instead of calling the Cloud REST API directly, so no API key/secret env
vars are needed: if the CLI is installed and logged in, the tool is available.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)

# Single source of truth for the default model. Referenced by both the input
# schema and every code path that reads `model`, so estimate_cost / estimate_runtime
# / execute can never silently diverge from the advertised default again.
# Names are CLI job types — see `higgsfield model list --video`.
_DEFAULT_MODEL = "seedance_2_0"

# Models advertised by the tool schema (all verified against `model list --video`).
_CLI_MODELS = [
    "seedance_2_0",
    "seedance_2_0_mini",
    "seedance_2_5",
    "seedance1_5",
    "kling3_0",
    "kling3_0_turbo",
    "kling2_6",
    "veo3_1",
    "veo3_1_lite",
    "grok_video",
    "grok_video_v15",
    "minimax_h3",
    "minimax_h3_max",
    "minimax_hailuo",
]

# Legacy schema names (pre-CLI Cloud API naming) → (cli job type, extra params).
_LEGACY_MODEL_ALIASES: dict[str, tuple[str, dict[str, str]]] = {
    "seedance_2.0": ("seedance_2_0", {}),
    "seedance_2.0_fast": ("seedance_2_0", {"mode": "fast"}),
    "kling_3.0": ("kling3_0", {}),
    "veo_3.1": ("veo3_1", {}),
}

# Legacy names that have no CLI equivalent.
_LEGACY_MODEL_GONE = {"sora_2", "wan_2.5", "soul_cinema"}


class HiggsFieldVideo(BaseTool):
    name = "higgsfield_video"
    version = "0.2.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "higgsfield"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "Install the Higgsfield CLI (https://www.higgsfield.ai/cli) and run:\n"
        "  higgsfield auth login\n"
        "  higgsfield workspace set <workspace_id>   # see: higgsfield workspace list\n"
        "No API key env vars are needed — the CLI's OAuth token is used."
    )
    agent_skills = ["higgsfield-generate", "higgsfield-soul-id", "seedance-2-0", "ai-video-gen"]

    capabilities = ["text_to_video", "image_to_video"]
    supports = {
        "text_to_video": True,
        "image_to_video": True,
        "character_consistency": True,
        "multi_model_routing": True,
        "native_audio": True,
        "cinematic_quality": True,
        "camera_direction": True,
        "lip_sync": True,
        "multi_shot": True,
    }
    best_for = [
        "preferred premium video gen on Higgsfield (Seedance 2.0 is the default model)",
        "cinematic trailers, teasers, and high-fidelity clips with native synchronized audio",
        "character-consistent video generation (Soul ID + Seedance 2.0 identity consistency)",
        "director-level camera control and multi-shot editing in a single generation",
        "lip-sync from quoted dialogue in prompts",
        "multi-model access through one CLI login (Seedance, Kling, Veo, Grok, MiniMax)",
    ]
    not_good_for = ["offline generation", "fine-grained model control", "budget projects without subscription"]
    fallback_tools = ["seedance_video", "seedance_replicate", "kling_video", "veo_video", "minimax_video"]
    quality_score = 0.9

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["text_to_video", "image_to_video"],
                "default": "text_to_video",
            },
            "model": {
                "type": "string",
                "enum": _CLI_MODELS,
                "default": _DEFAULT_MODEL,
                "description": "CLI job type (see `higgsfield model list --video`). Defaults to Seedance 2.0 — see .agents/skills/seedance-2-0/",
            },
            "duration": {
                "type": "string",
                "enum": ["5", "10", "15"],
                "default": "5",
                "description": "Duration in seconds (availability varies by model)",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["16:9", "9:16", "1:1", "21:9"],
                "default": "16:9",
            },
            "image_url": {
                "type": "string",
                "description": "Reference image for image_to_video: local path, http(s) URL, or Higgsfield upload UUID",
            },
            "resolution": {
                "type": "string",
                "description": "Optional model-dependent resolution (e.g. 720p/1080p for seedance_2_0)",
            },
            "mode": {
                "type": "string",
                "description": "Optional model-dependent mode (e.g. std/fast for seedance_2_0, std/pro/4k for kling3_0)",
            },
            "output_path": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=500, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    idempotency_key_fields = ["prompt", "model", "operation", "duration"]
    side_effects = ["writes video file to output_path", "spends Higgsfield credits via the CLI"]
    user_visible_verification = ["Watch generated clip for motion coherence and visual quality"]

    # ------------------------------------------------------------------ CLI helpers

    def _run_cli(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["higgsfield", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _run_cli_json(self, args: list[str], timeout: int = 120) -> dict[str, Any]:
        proc = self._run_cli([*args, "--json"], timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "unknown CLI error").strip())
        out = proc.stdout.strip()
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", out, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise RuntimeError(f"Could not parse CLI JSON output: {out[:300]}")

    def _cli_ready(self) -> bool:
        if not shutil.which("higgsfield"):
            return False
        try:
            proc = self._run_cli(["auth", "token"], timeout=15)
        except Exception:
            return False
        return proc.returncode == 0 and bool(proc.stdout.strip())

    def get_status(self) -> ToolStatus:
        if self._cli_ready():
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    # ------------------------------------------------------------------ estimates

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        resolved = self._resolve_model(inputs.get("model", _DEFAULT_MODEL))
        model = resolved[0] if resolved else inputs.get("model", _DEFAULT_MODEL)
        duration = int(inputs.get("duration", "5"))
        # Rough USD equivalents of Higgsfield credit pricing per 5s clip.
        base_costs = {
            "seedance_2_0": 0.80,
            "seedance_2_0_mini": 0.40,
            "seedance_2_5": 1.00,
            "seedance1_5": 0.50,
            "kling3_0": 0.35,
            "kling3_0_turbo": 0.25,
            "kling2_6": 0.20,
            "veo3_1": 0.50,
            "veo3_1_lite": 0.30,
            "grok_video": 0.30,
            "grok_video_v15": 0.35,
            "minimax_h3": 0.15,
            "minimax_h3_max": 0.25,
            "minimax_hailuo": 0.15,
        }
        base = base_costs.get(model, 0.30)
        return base * (duration / 5)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        resolved = self._resolve_model(inputs.get("model", _DEFAULT_MODEL))
        model = resolved[0] if resolved else inputs.get("model", _DEFAULT_MODEL)
        if model in ("veo3_1", "seedance_2_0", "seedance_2_5", "kling3_0"):
            return 120.0
        return 60.0

    # ------------------------------------------------------------------ model resolution

    def _resolve_model(self, model: str) -> tuple[str, dict[str, str]] | None:
        """Map a schema/legacy model name to (cli job type, extra params)."""
        if model in _CLI_MODELS:
            return model, {}
        if model in _LEGACY_MODEL_ALIASES:
            return _LEGACY_MODEL_ALIASES[model]
        return None

    # ------------------------------------------------------------------ execute

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not self._cli_ready():
            return ToolResult(
                success=False,
                error="Higgsfield CLI not installed or not logged in. " + self.install_instructions,
            )

        start = time.time()
        operation = inputs.get("operation", "text_to_video")
        requested_model = inputs.get("model", _DEFAULT_MODEL)

        if requested_model in _LEGACY_MODEL_GONE:
            return ToolResult(
                success=False,
                error=(
                    f"Model {requested_model!r} is not exposed by the Higgsfield CLI. "
                    f"Available: {', '.join(_CLI_MODELS)}"
                ),
            )
        resolved = self._resolve_model(requested_model)
        if not resolved:
            return ToolResult(
                success=False,
                error=f"Unknown model {requested_model!r}. Available: {', '.join(_CLI_MODELS)}",
            )
        job_type, extra_params = resolved

        # Resolve image input for image_to_video. The CLI accepts a local path
        # (auto-uploaded) or an upload UUID; http(s) URLs are downloaded first.
        image_ref = inputs.get("image_url")
        tmp_image: str | None = None
        if operation == "image_to_video" and image_ref:
            if image_ref.startswith(("http://", "https://")):
                try:
                    import requests

                    resp = requests.get(image_ref, timeout=60)
                    resp.raise_for_status()
                    suffix = ".png"
                    ctype = resp.headers.get("Content-Type", "")
                    if "jpeg" in ctype or "jpg" in ctype:
                        suffix = ".jpg"
                    elif "webp" in ctype:
                        suffix = ".webp"
                    fd, tmp_image = tempfile.mkstemp(suffix=suffix)
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(resp.content)
                    image_ref = tmp_image
                except Exception as e:
                    return ToolResult(success=False, error=f"Failed to fetch image_url: {e}")

        create_args = ["generate", "create", job_type, "--prompt", inputs["prompt"]]
        if inputs.get("duration"):
            create_args += ["--duration", str(int(inputs["duration"]))]
        if inputs.get("aspect_ratio"):
            create_args += ["--aspect-ratio", inputs["aspect_ratio"]]
        if inputs.get("resolution"):
            create_args += ["--resolution", inputs["resolution"]]
        if inputs.get("mode"):
            create_args += ["--mode", inputs["mode"]]
        for key, value in extra_params.items():
            create_args += [f"--{key.replace('_', '-')}", value]
        if operation == "image_to_video" and image_ref:
            create_args += ["--start-image", image_ref]

        try:
            job = self._run_cli_json(create_args, timeout=300)  # may include an image upload
            job_id = job.get("id")
            if not job_id:
                return ToolResult(success=False, error=f"CLI did not return a job id: {job}")

            wait = self._run_cli(
                ["generate", "wait", job_id, "--quiet", "--timeout", "20m"],
                timeout=1300,
            )
            if wait.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"Higgsfield job {job_id} failed/timed out: {(wait.stderr or wait.stdout).strip()[:300]}",
                )

            final = self._run_cli_json(["generate", "get", job_id], timeout=60)
            status = final.get("status", "")
            if status != "completed":
                return ToolResult(
                    success=False,
                    error=f"Higgsfield job {job_id} ended with status {status!r}",
                )
            video_url = final.get("result_url") or final.get("min_result_url")
            if not video_url:
                return ToolResult(success=False, error=f"Higgsfield job {job_id} has no result_url")

            import requests

            video_response = requests.get(video_url, timeout=120)
            video_response.raise_for_status()

            output_path = Path(inputs.get("output_path", "higgsfield_output.mp4"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video_response.content)

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Higgsfield CLI call timed out.")
        except Exception as e:
            return ToolResult(success=False, error=f"Higgsfield video generation failed: {e}")
        finally:
            if tmp_image and os.path.exists(tmp_image):
                os.unlink(tmp_image)

        from tools.video._shared import probe_output

        probed = probe_output(output_path)
        return ToolResult(
            success=True,
            data={
                "provider": "higgsfield",
                "model": job_type,
                "requested_model": requested_model,
                "job_id": job_id,
                "prompt": inputs["prompt"],
                "operation": operation,
                "aspect_ratio": inputs.get("aspect_ratio", "16:9"),
                "output": str(output_path),
                "output_path": str(output_path),
                "format": "mp4",
                **probed,
            },
            artifacts=[str(output_path)],
            cost_usd=self.estimate_cost(inputs),
            duration_seconds=round(time.time() - start, 2),
            model=job_type,
        )
