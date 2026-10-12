"""Desktop launch plus bounded, synthetic-output-only validation commands."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import asdict
from pathlib import Path

import cv2

from trickroom.assets.gltf import load_asset
from trickroom.assets.motion import MotionOptions
from trickroom.assets.retarget import AvatarInstance
from trickroom.camera import Source
from trickroom.credentials import load_defaults
from trickroom.demo import demo_observation
from trickroom.models import default_model_directory, ensure_models
from trickroom.raster import close_renderer
from trickroom.render import Renderer, StageOptions
from trickroom.runtime import Runtime


def positive_seconds(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0 < result <= 86400:
        raise argparse.ArgumentTypeError("Seconds must be finite and between 0 and 86400.")
    return result


def render_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use WIDTHxHEIGHT, for example 960x720.") from error
    if not 320 <= width <= 4096 or not 240 <= height <= 4096 or width % 2 or height % 2:
        raise argparse.ArgumentTypeError("Video size must be even and within 320x240 to 4096x4096.")
    return width, height


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="TrickRoom: full-body/face tracking on a completely synthetic stage.",
    )
    result.add_argument(
        "--source",
        default=os.environ.get("TRICKROOM_CAMERA_URL", ""),
        help="IP Webcam /video URL, device number or video path. Never logged.",
    )
    result.add_argument("--rotate", choices=("none", "left", "right", "180"), default="none")
    result.add_argument("--mirror", action=argparse.BooleanOptionalAction, default=True)
    result.add_argument("--demo", action="store_true", help="Synthetic motion; opens no camera.")
    result.add_argument(
        "--demo-cropped", action="store_true", help="Demonstrate cropped lower legs."
    )
    result.add_argument(
        "--headless", action="store_true", help="Run for --seconds without windows."
    )
    result.add_argument(
        "--seconds",
        type=positive_seconds,
        help="Headless time limit (default 10s), or source duration for video export.",
    )
    result.add_argument(
        "--render-video",
        type=Path,
        help="Offline reference recording to a new synthetic MP4; no UI.",
    )
    result.add_argument(
        "--render-size", type=render_size, default=(960, 720), metavar="WIDTHxHEIGHT"
    )
    result.add_argument(
        "--start-seconds", type=float, default=0.0, help="Video-export source start time."
    )
    result.add_argument(
        "--clean-output",
        action="store_true",
        help="Video export without the review HUD/head inset.",
    )
    result.add_argument(
        "--snapshot", type=Path, help="Explicitly save only the synthetic output PNG."
    )
    result.add_argument(
        "--report", type=Path, help="Write aggregate timing/counts, no URLs/landmarks."
    )
    result.add_argument("--models", type=Path, default=default_model_directory())
    result.add_argument(
        "--download-models", action="store_true", help="Fetch/verify pinned models; exit."
    )
    result.add_argument(
        "--tracking-size", type=int, choices=(512, 640, 768, 960, 1280), default=768
    )
    imports = result.add_mutually_exclusive_group()
    imports.add_argument("--avatar", type=Path, help="Prepared Blender-exported GLB model.")
    imports.add_argument(
        "--validate-avatar", type=Path, help="Preflight a GLB and print its report; no camera."
    )
    result.add_argument(
        "--avatar-profile", type=Path, help="Optional version1 bone/shape mapping JSON."
    )
    result.add_argument(
        "--avatar-mode", default="live", help="live, bind, or an exported clip name."
    )
    result.add_argument(
        "--rig-motion",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enhanced GLB rig motion; --no-rig-motion uses the legacy image-space path.",
    )
    result.add_argument("--rig-space", choices=("world", "image"), default="world")
    result.add_argument("--rig-constraints", action=argparse.BooleanOptionalAction, default=True)
    result.add_argument(
        "--relax-missing",
        action="store_true",
        help="Opt in to held/rest GLB limbs; these are never counted as detections.",
    )
    result.add_argument(
        "--face-response",
        action="store_true",
        help="Preset face response. Personal calibration is session-local in Studio.",
    )
    return result


def save_png(path: Path, image) -> None:
    if path.suffix.lower() != ".png":
        raise ValueError("Synthetic snapshots must use the .png extension.")
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise OSError("Could not encode synthetic output.")
    path.write_bytes(encoded.tobytes())


def headless(args: argparse.Namespace) -> int:
    is_demo = args.demo
    model_preview = args.avatar is not None and args.avatar_mode != "live"
    if not is_demo and not args.source and not model_preview:
        raise ValueError("Headless tracking requires --source or explicitly --demo.")
    runtime = None
    renderer = Renderer()
    renderer.motion_options = MotionOptions(
        enabled=args.rig_motion,
        space=args.rig_space,
        relax_missing=args.relax_missing,
        constrain_limbs=args.rig_constraints,
    )
    renderer.face_response.enabled = args.face_response
    frames = 0
    started = time.perf_counter()
    deadline = started + (args.seconds if args.seconds is not None else 10.0)
    last_state = None
    image = None
    report = None
    result = 0
    try:
        if args.avatar:
            renderer.load_model(args.avatar, args.avatar_profile)
            renderer.imported.set_mode(args.avatar_mode, started)
        if not is_demo and not model_preview:
            credentials = load_defaults()
            runtime = Runtime(
                Source.parse(
                    args.source,
                    credentials.username,
                    credentials.password,
                ),
                args.models,
                args.rotate,
                args.tracking_size,
            )
            runtime.start()
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            state = (
                demo_observation(now - started, now, cropped=args.demo_cropped)
                if is_demo
                else runtime.observation
                if runtime
                else None
            )
            last_state = state
            image = renderer.render(
                state,
                now=now,
                options=StageOptions(mirror=args.mirror),
                demo=is_demo,
                replay=runtime is not None and runtime.camera.source.kind == "file",
                connection="RUNNING",
            )
            frames += 1
            if runtime is not None and runtime.status.state in ("ERROR", "ENDED"):
                break
            time.sleep(max(0.0, 1 / 30 - (time.perf_counter() - now)))
        status = runtime.status if runtime else None
        if status and status.state == "ERROR":
            print(status.message)
            result = 2
        if runtime and (status.frames == 0 or last_state is None):
            print("No input frames reached inference. Check the app, source and model setup.")
            result = 2
        elif runtime and status.state != "ENDED" and last_state.age(time.perf_counter()) > 0.6:
            print("Input became stale before the check finished. The stage cleared safely.")
            result = 2
        if args.snapshot and image is not None:
            save_png(args.snapshot, image)
        report = {
            "mode": "model-preview"
            if model_preview
            else "synthetic-demo"
            if is_demo
            else "camera-or-replay",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "rendered_frames": frames,
            "inference": asdict(status) if status else None,
            "capture": asdict(runtime.camera.status) if runtime else None,
            "raw_pixels_saved": False,
            "end_to_end_latency_measured": False,
            "last_observation_fresh": last_state is not None
            and last_state.age(
                time.perf_counter(),
            )
            <= 0.6,
            "avatar": renderer.imported.asset.report() if renderer.imported else "built-in",
            "rig_motion": asdict(renderer.motion_options),
            "face_response_enabled": args.face_response,
            "presentation_states": renderer._imported_frame.evaluation.tracking_states
            if renderer._imported_frame is not None
            else None,
        }
    finally:
        if runtime is not None:
            runtime.stop()
            runtime.join()
            if runtime.alive:
                print("Capture/inference did not stop within the shutdown deadline.")
                result = 2
            if runtime.status.forced_shutdown:
                print(runtime.status.message)
                result = 2
        close_renderer()
    if report is not None:
        report["shutdown_complete"] = runtime is None or not runtime.alive
        report["worker_shutdown"] = (
            {
                "pid": runtime.status.worker_pid,
                "exit_code": runtime.status.worker_exit_code,
                "forced": runtime.status.forced_shutdown,
            }
            if runtime
            else None
        )
        report["exit_code"] = result
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.render_video is not None:
            if args.download_models or args.validate_avatar:
                raise ValueError("Run model download/validation separately from video export.")
            from trickroom.video_export import export_video

            return export_video(args, save_png)
        if args.start_seconds or args.clean_output or args.render_size != (960, 720):
            raise ValueError("Export start/size/clean options require --render-video.")
        if args.download_models:
            for path in ensure_models(args.models, download=True):
                print(f"Verified model: {path.name}")
            return 0
        if args.validate_avatar:
            sidecar = args.validate_avatar.with_suffix(".trickroom.json")
            asset = load_asset(
                args.validate_avatar,
                args.avatar_profile or (sidecar if sidecar.is_file() else None),
            )
            AvatarInstance(asset)
            report = asset.report()
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 0
        if (args.avatar_profile or args.avatar_mode != "live") and args.avatar is None:
            raise ValueError(
                "--avatar-profile and --avatar-mode require --avatar or --validate-avatar."
            )
        if args.headless:
            return headless(args)
        if args.report or args.snapshot:
            raise ValueError("--report and --snapshot require --headless.")
        import tkinter as tk

        from trickroom.studio import Studio

        root = tk.Tk()
        studio = None
        try:
            studio = Studio(
                root,
                args.models,
                source="" if args.demo else args.source,
                rotation=args.rotate,
                mirror=args.mirror,
                demo=args.demo or not args.source,
                tracking_size=args.tracking_size,
                avatar=args.avatar,
                avatar_profile=args.avatar_profile,
                avatar_mode=args.avatar_mode,
                rig_motion=args.rig_motion,
                rig_space=args.rig_space,
                relax_missing=args.relax_missing,
                rig_constraints=args.rig_constraints,
                face_response=args.face_response,
            )
            credentials = load_defaults()
            studio.username.set(credentials.username)
            studio.password.set(credentials.password)
            studio.crop_demo.set(args.demo_cropped)
            root.mainloop()
        finally:
            if studio is not None and studio.runtime is not None:
                studio.runtime.stop()
                studio.runtime.join()
                if studio.runtime.alive:
                    print("TrickRoom: a native worker exceeded the shutdown deadline.")
                    studio.exit_code = 2
            close_renderer()
            try:
                root.destroy()
            except tk.TclError:
                pass
        return studio.exit_code
    except (ValueError, FileNotFoundError, OSError, RuntimeError, cv2.error) as error:
        print(f"TrickRoom: {error}")
        return 2
    except KeyboardInterrupt:
        print("TrickRoom stopped.")
        return 130
