"""Synthetic-only stage. Camera pixels cannot enter the character renderer."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from trickroom.assets.gltf import load_asset
from trickroom.assets.motion import MotionOptions
from trickroom.assets.presentation import head_presentation, present
from trickroom.assets.retarget import AvatarInstance
from trickroom.avatar import Footprint, HeadPlacement, character_mesh, color, rasterize
from trickroom.avatar import draw_head as draw_head
from trickroom.face_response import FaceResponse
from trickroom.raster import clear_model_textures, draw_textured
from trickroom.room import RoomBackground, draw_foot_shadows, room_background
from trickroom.state import BODY_CONNECTIONS, Observation, Point

BG = color("0a121c")
GRID = color("172735")
INK = color("080e18")
MINT = color("79efc5")
VIOLET = color("b8a4ff")
WHITE = color("dfebec")
MUTED = color("76909e")
AMBER = color("edba75")


@dataclass(frozen=True)
class StageOptions:
    mirror: bool = True
    outline: bool = False
    skeleton: bool = False
    grid: bool = True
    head_detail: bool = True
    hud: bool = True


DEFAULT_OPTIONS = StageOptions()


@dataclass(frozen=True)
class Viewport:
    x: float
    y: float
    width: float
    height: float

    def point(self, p: Point) -> tuple[int, int]:
        return round(self.x + p.x * self.width), round(self.y + p.y * self.height)


def viewport(size: tuple[int, int], source: tuple[int, int], hud: bool) -> Viewport:
    w, h = size
    sw, sh = source
    padding, top, bottom = 26, 56 if hud else 18, 40 if hud else 18
    scale = min((w - padding * 2) / max(sw, 1), (h - top - bottom) / max(sh, 1))
    return Viewport(
        (w - sw * scale) / 2,
        top + (h - top - bottom - sh * scale) / 2,
        sw * scale,
        sh * scale,
    )


def _mix(value: tuple[int, int, int], gain: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(v * gain))) for v in value)


def _text(image, label: str, xy: tuple[int, int], tint=WHITE, scale: float = 0.42) -> None:
    cv2.putText(image, label, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, tint, 1, cv2.LINE_AA)


def _head_anchor(state: Observation, view: Viewport) -> tuple | None:
    if state.face is not None:
        face = state.face
        height = face.height * view.height
        center = view.point(face.center)
        # Character proportions follow the sheet, not a tight human-face overlay.
        return (
            (center[0], center[1] + height * 0.28),
            max(12, face.width * view.width * 1.18, height * 1.17),
            max(16, height * 1.48),
            face,
            0.0,
        )
    nose = state.joint(0)
    left_ear, right_ear = state.joint(7), state.joint(8)
    left_eye, right_eye = state.joint(2), state.joint(5)
    if nose is None:
        return None
    a, b = view.point(nose), view.point(nose)
    if left_ear is not None and right_ear is not None:
        a, b = view.point(left_ear), view.point(right_ear)
    elif left_eye is not None and right_eye is not None:
        a, b = view.point(left_eye), view.point(right_eye)
    span = math.dist(a, b)
    shoulders = (state.joint(11), state.joint(12))
    shoulder_width = 0.0
    if all(p is not None for p in shoulders):
        shoulder_width = math.dist(view.point(shoulders[0]), view.point(shoulders[1]))
    width = max(span * (1.5 if left_ear and right_ear else 3.2), shoulder_width * 0.80, 16)
    position = view.point(nose)
    roll = 0.0
    if left_eye is not None and right_eye is not None:
        left, right = view.point(left_eye), view.point(right_eye)
        roll = -math.degrees(math.atan2(left[1] - right[1], max(1.0, left[0] - right[0])))
    return ((position[0], position[1] + width * 0.20), width, width * 1.26, None, roll)


class Renderer:
    def __init__(self) -> None:
        self.imported: AvatarInstance | None = None
        self._imported_frame = None
        self.motion_options = MotionOptions()
        self.face_response = FaceResponse()
        self._generation: int | None = None

    def reset_motion(self, *, preserve_face_calibration: bool = False) -> None:
        if self.imported is not None:
            self.imported.reset_calibration()
        self._imported_frame = None
        self._generation = None
        if preserve_face_calibration:
            self.face_response.apply(None, 0.0)
        else:
            self.face_response.reset()

    def load_model(self, path: Path, profile: Path | None = None) -> dict:
        sidecar = path.with_suffix(".trickroom.json")
        profile = profile or (sidecar if sidecar.is_file() else None)
        asset = load_asset(path, profile)
        instance = AvatarInstance(asset)
        self.set_model(instance)
        return asset.report()

    def set_model(self, instance: AvatarInstance) -> None:
        clear_model_textures()
        self.imported = instance
        self._imported_frame = None

    def use_builtin(self) -> None:
        self.imported = None
        self._imported_frame = None
        clear_model_textures()

    def render(
        self,
        state: Observation | None,
        size: tuple[int, int] = (960, 720),
        *,
        now: float,
        options: StageOptions = DEFAULT_OPTIONS,
        demo: bool = False,
        replay: bool = False,
        connection: str = "READY",
    ) -> NDArray[np.uint8]:
        width, height = size
        if width < 320 or height < 240 or width > 4096 or height > 4096:
            raise ValueError("Stage size must be between 320x240 and 4096x4096.")
        if state is not None:
            if self._generation is not None and self._generation != state.generation:
                self.reset_motion(preserve_face_calibration=True)
            self._generation = state.generation
        paused = replay and connection == "PAUSED"
        if paused and state is not None and state.media_time is not None:
            now = state.completed_at
        state = self.face_response.apply(state, now)
        if self.imported is not None:
            self.imported.configure_motion(self.motion_options)
        internal_width = min(width, max(640, round(width * 240 / height)))
        internal_height = round(height * internal_width / width)
        iw, ih = internal_width, internal_height
        room = room_background(iw, ih, options.hud) if options.grid else None
        scene = room.pixels.copy() if room else np.full((ih, iw, 3), BG, np.uint8)
        fresh = state is not None and state.age(now) <= 0.6
        if not fresh and self.imported is not None and self.motion_options.enabled:
            self.imported.motion.reset()
        model_preview = self.imported is not None and self.imported.preview
        self._imported_frame = None
        if self.imported is not None and (fresh or model_preview):
            source_size = state.frame_size if fresh and not model_preview else (900, 1200)
            model_view = viewport((iw, ih), source_size, options.hud)
            self._imported_frame = present(
                self.imported,
                state if fresh else None,
                model_view,
                now,
            )
            if self._imported_frame is not None:
                if room:
                    draw_foot_shadows(scene, room, self._imported_frame.footprints)
                draw_textured(scene, self._imported_frame.batches)
        elif fresh:
            self._body(
                scene, state, viewport((iw, ih), state.frame_size, options.hud), options, room
            )
        if options.mirror:
            scene = cv2.flip(scene, 1)
        if options.head_detail and options.hud:
            self._head_detail(scene, state if fresh else None, options.mirror, demo, replay, paused)
        if options.hud:
            self._hud(scene, state, now, demo, connection, replay)
            presentation_states = (
                self._imported_frame.evaluation.tracking_states
                if self._imported_frame is not None
                else None
            )
            unmeasured = (
                sum(
                    value in ("HELD", "RETURNING", "REST") for value in presentation_states.values()
                )
                if presentation_states
                else 0
            )
            if unmeasured:
                _text(
                    scene,
                    f"RIG: {unmeasured} HELD / REST REGIONS - NOT TRACKED",
                    (30, ih - 49),
                    AMBER,
                    0.31,
                )
            elif (
                fresh
                and state.joints
                and not all(state.joint(index) is not None for index in (27, 28, 31, 32))
            ):
                _text(scene, "OFF-FRAME / LOW-CONFIDENCE JOINTS HIDDEN", (30, ih - 49), AMBER, 0.31)
        elif demo or model_preview or replay:
            _text(
                scene,
                "MODEL PREVIEW - NOT CAMERA TRACKING"
                if model_preview
                else "PAUSED VIDEO REPLAY - NOT LIVE CAMERA"
                if paused
                else "VIDEO REPLAY - NOT LIVE CAMERA"
                if replay
                else "DEMO - NOT CAMERA TRACKING",
                (12, 20),
                AMBER,
                0.42,
            )
        if not model_preview and (not fresh or (state.visible_joints < 4 and state.face is None)):
            label = "TRACKING STALE" if state is not None and not fresh else "WAITING FOR TRACKING"
            if state is None and connection in ("READY", "STOPPED"):
                label = "YOUR MOVEMENT. A NEW FORM."
            x = max(16, iw // 2 - 145)
            _text(scene, label, (x, ih // 2), WHITE, 0.59)
            _text(scene, "Camera pixels never enter this stage.", (x, ih // 2 + 28), MUTED, 0.42)
        return cv2.resize(scene, size, interpolation=cv2.INTER_NEAREST)

    def _body(
        self,
        image,
        state: Observation,
        view: Viewport,
        options: StageOptions,
        room: RoomBackground | None = None,
    ) -> None:
        if options.outline:
            for contour in state.contours:
                points = np.int32([view.point(p) for p in contour])
                cv2.fillPoly(image, [points], color("11252c"))
                cv2.polylines(image, [points], True, color("41867f"), 1, cv2.LINE_8)
        positions = {
            i: np.array((*view.point(point), -point.z * view.width), dtype=float)
            for i in range(len(state.joints))
            if (point := state.joint(i)) is not None
        }
        anchor = _head_anchor(state, view)
        head = None
        if anchor is not None:
            center, width, height, face, roll = anchor
            depth = float(positions[0][2]) if 0 in positions else width * 0.4
            head = HeadPlacement((*center, depth), width, height, face, roll)
        footprints: list[Footprint] = []
        mesh = character_mesh(
            positions,
            head,
            view.width * 0.26,
            footprints=footprints if room else None,
        )
        if room is not None:
            draw_foot_shadows(image, room, footprints)
        rasterize(image, mesh)
        if options.skeleton:
            for a, b in BODY_CONNECTIONS:
                if a in positions and b in positions:
                    cv2.line(
                        image,
                        tuple(np.int32(positions[a][:2])),
                        tuple(np.int32(positions[b][:2])),
                        _mix(WHITE, 0.8),
                        1,
                    )
            for index, xyz in positions.items():
                if index < 11:
                    continue
                xy = tuple(np.int32(xyz[:2]))
                tint = MINT if index % 2 else VIOLET
                cv2.circle(image, xy, 3 if index < 29 else 2, INK, -1)
                cv2.circle(image, xy, 2 if index < 29 else 1, tint, 1)

    def _head_detail(
        self,
        image,
        state: Observation | None,
        mirror: bool,
        demo: bool,
        replay: bool = False,
        paused: bool = False,
    ) -> None:
        h, w = image.shape[:2]
        x, y = w - 119, 63
        if h < 350:
            return
        cv2.rectangle(image, (x, y), (w - 12, y + 131), color("10202c"), -1)
        cv2.rectangle(image, (x, y), (w - 12, y + 131), GRID, 1)
        face = state.face if state else None
        _text(
            image, "GLB / HEAD" if self.imported else "HEAD / DETAIL", (x + 9, y + 17), MUTED, 0.32
        )
        tile = np.full((92, 101, 3), color("10202c"), np.uint8)
        if self.imported is not None:
            if self._imported_frame is not None:
                draw_textured(
                    tile,
                    head_presentation(
                        self.imported,
                        self._imported_frame.evaluation,
                        101,
                        92,
                    ),
                )
        else:
            draw_head(tile, (50, 49), 60, 74, face)
        image[y + 25 : y + 117, x + 3 : x + 104] = cv2.flip(tile, 1) if mirror else tile
        label = (
            "MODEL PREVIEW"
            if self.imported and self.imported.preview
            else "SCRIPTED FACE"
            if demo and face
            else "PAUSED FACE"
            if paused and face
            else "FACE / REPLAY"
            if replay and face
            else "FACE LIVE"
            if face
            else "FACE UNAVAILABLE"
        )
        _text(image, label, (x + 8, y + 121), MINT if face else AMBER, 0.31)

    def _hud(
        self,
        image,
        state: Observation | None,
        now: float,
        demo: bool,
        connection: str,
        replay: bool = False,
    ) -> None:
        h, w = image.shape[:2]
        cv2.rectangle(image, (0, 0), (w, 46), BG, -1)
        cv2.line(image, (16, 45), (w - 16, 45), GRID, 1)
        _text(image, "TRICKROOM", (18, 26), MINT, 0.64)
        _text(
            image,
            "04 / BLENDER MODEL" if self.imported else "03 / CALIBRATION ROOM",
            (180, 25),
            MUTED,
            0.34,
        )
        label = (
            "MODEL / NOT TRACKING"
            if self.imported and self.imported.preview
            else "DEMO / NOT CAMERA"
            if demo
            else "REPLAY / PAUSED"
            if replay and connection == "PAUSED"
            else "VIDEO REPLAY"
            if replay
            else "SYNTHETIC OUTPUT"
        )
        _text(image, label, (w - 169, 25), AMBER if demo else WHITE, 0.36)
        cv2.rectangle(image, (0, h - 34), (w, h), BG, -1)
        cv2.line(image, (16, h - 34), (w - 16, h - 34), GRID, 1)
        status = state.body_status(now) if state else connection
        count = state.visible_joints if state and state.age(now) <= 0.6 else 0
        model_preview = self.imported is not None and self.imported.preview
        _text(
            image,
            "MODEL PREVIEW / NO LIVE POSE"
            if model_preview
            else f"{status}   {count:02d}/33 JOINTS",
            (18, h - 13),
            MINT if status == "FULL BODY" else AMBER,
            0.36,
        )
        _text(
            image,
            "GLB / " + self.imported.mode[:18] if self.imported else "REFERENCE / 01",
            (w - 160, h - 13),
            MUTED,
            0.33,
        )
