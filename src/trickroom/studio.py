"""Synthetic presentation plus isolated, explicitly enabled private diagnostic windows."""

from __future__ import annotations

import json
import math
import queue
import threading
import time
import tkinter as tk
from collections import Counter
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText

import cv2
from PIL import Image, ImageTk

from trickroom import debug_views
from trickroom.assets.gltf import load_asset
from trickroom.assets.motion import MotionOptions
from trickroom.assets.presentation import camera_batches
from trickroom.assets.profile import AssetError
from trickroom.assets.retarget import AvatarInstance
from trickroom.camera import Source
from trickroom.demo import demo_observation
from trickroom.face_response import CHANNELS
from trickroom.ghostcam import MAX_FOV, MIN_FOV, CameraCommand, GhostCamera
from trickroom.graphics_worker import GraphicsWorker
from trickroom.raster import draw_textured
from trickroom.render import Renderer, StageOptions
from trickroom.room import camera_room
from trickroom.runtime import Runtime
from trickroom.state import Observation


def format_replay_time(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--"
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class CollapsibleSection(ttk.Frame):
    def __init__(self, parent, title: str, *, expanded: bool = False) -> None:
        super().__init__(parent)
        self.title = title
        self.expanded = expanded
        self.header = ttk.Button(self, style="Section.TButton", command=self.toggle, takefocus=True)
        self.header.pack(fill="x")
        self.header.bind("<Return>", self._toggle_from_keyboard)
        self.body = ttk.Frame(self, padding=(0, 4, 0, 6))
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        if not expanded:
            focused = self.focus_get()
            if focused is not None and (
                focused is self.body or str(focused).startswith(str(self.body) + ".")
            ):
                self.header.focus_set()
        self.expanded = expanded
        self.header.configure(text=f"{'[-]' if expanded else '[+]'} {self.title}")
        if expanded:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()

    def toggle(self) -> None:
        self.set_expanded(not self.expanded)

    def _toggle_from_keyboard(self, _event) -> str:
        self.toggle()
        return "break"


class Studio:
    def __init__(
        self,
        root: tk.Tk,
        models: Path,
        *,
        source: str = "",
        rotation: str = "none",
        mirror: bool = True,
        demo: bool = True,
        tracking_size: int = 768,
        avatar: Path | None = None,
        avatar_profile: Path | None = None,
        avatar_mode: str = "live",
        rig_motion: bool = True,
        rig_space: str = "world",
        relax_missing: bool = False,
        rig_constraints: bool = True,
        face_response: bool = False,
    ) -> None:
        self.root = root
        self.models = models
        self.tracking_size = tracking_size
        self.renderer = Renderer()
        self.rig_motion = tk.BooleanVar(value=rig_motion)
        self.rig_space = tk.StringVar(value=rig_space)
        self.relax_missing = tk.BooleanVar(value=relax_missing)
        self.rig_constraints = tk.BooleanVar(value=rig_constraints)
        self.motion_info = tk.StringVar(value="Rig motion requires an imported GLB.")
        self.face_shaping = tk.BooleanVar(value=face_response)
        self.face_response_info = tk.StringVar()
        self.face_gains = {name: tk.DoubleVar(value=1) for name in CHANNELS}
        self._model_thread: threading.Thread | None = None
        self._model_pending = False
        self._model_generation = 0
        self._model_results = queue.Queue(maxsize=1)
        self._model_report = None
        self._model_commit = None
        self.model_info = tk.StringVar(value="Built-in reference character")
        self.model_profile = tk.StringVar(value=str(avatar_profile) if avatar_profile else "")
        self.model_mode = tk.StringVar(value="live")
        self.runtime: Runtime | None = None
        self.demo = demo
        self._demo_start = time.perf_counter()
        self._closing = False
        self._shutdown_started = 0.0
        self.exit_code = 0
        self._disconnecting = False
        self._tick_id: str | None = None
        self._render_tick_id: str | None = None
        self._render_epoch = 0
        self._render_commands = []
        self._draw_pending = None
        self._displayed = {}
        self._view_due = dict.fromkeys(("preview", "output", *debug_views.TITLES), 0.0)
        self._last_telemetry = 0.0
        self._output_window: tk.Toplevel | None = None
        self._output_label: ttk.Label | None = None
        self._photo = None
        self._output_photo = None
        self._render_fps = 0.0
        self._last_tick = 0.0
        self.debug_options = {name: tk.BooleanVar(value=False) for name in debug_views.TITLES}
        self._debug_windows: dict[str, tuple[tk.Toplevel, ttk.Label]] = {}
        self._debug_photos = {}
        self._test_video: Path | None = None
        self._timeline_visible = False
        self._playback_config = None
        self._scrubbing = False
        self._pending_seek: float | None = None
        self._requested_paused: bool | None = None
        self.playback_position = tk.DoubleVar(value=0)
        self.playback_time = tk.StringVar(value="00:00 / --:--")
        self.source = tk.StringVar(value=source)
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.rotation = tk.StringVar(value=rotation)
        self.mirror = tk.BooleanVar(value=mirror)
        self.outline = tk.BooleanVar(value=False)
        self.skeleton = tk.BooleanVar(value=False)
        self.detail = tk.BooleanVar(value=True)
        self.grid = tk.BooleanVar(value=True)
        self.smoothing = tk.BooleanVar(value=True)
        self.crop_demo = tk.BooleanVar(value=False)
        self.mode_label = tk.StringVar(value="DEMO / no camera access" if demo else "READY")
        self.message = tk.StringVar(value="Paste the IP Webcam video URL, then Connect.")
        self.capture_info = tk.StringVar(value="Capture --   /   Inference --")
        self.frame_info = tk.StringVar(value="No input frames")
        self.body_info = tk.StringVar(value="Body: demonstration" if demo else "Body: waiting")
        self.face_info = tk.StringVar(value="Face: demonstration" if demo else "Face: waiting")
        self.pose_info = tk.StringVar(value="Pitch --   Yaw --   Roll --")
        self.meters = {
            name: tk.DoubleVar(value=0) for name in ("Left blink", "Right blink", "Mouth", "Smile")
        }
        self.ghost_camera = GhostCamera()
        self.ghost_enabled = tk.BooleanVar(value=False)
        self.ghost_fov = tk.DoubleVar(value=self.ghost_camera.fov_y)
        self.ghost_speed = tk.DoubleVar(value=self.ghost_camera.speed)
        self.ghost_info = tk.StringVar(value="Ghost camera off. The stage view is unchanged.")
        self._ghost_keys: set[str] = set()
        self._ghost_look = [0.0, 0.0]
        self._ghost_pointer: tuple[int, int] | None = None
        self._ghost_captured = False
        self._ghost_clock: float | None = None
        self._configure()
        self._build()
        self.render_worker = GraphicsWorker(self.renderer)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", self._escape)
        self.root.bind("<KeyPress>", self._ghost_key_press, add="+")
        self.root.bind("<KeyRelease>", self._ghost_key_release, add="+")
        self.preview_frame.bind("<Button-1>", self._capture_pointer, add="+")
        self.preview_frame.bind("<Motion>", self._ghost_motion, add="+")
        self._tick()
        self._render_tick()
        if avatar is not None:
            self.root.after(50, lambda: self.load_model(avatar, avatar_profile, avatar_mode))
        if source and not demo:
            self.root.after(100, self.connect)

    def _configure(self) -> None:
        self.root.title("TrickRoom | Tracking Lab")
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width, height = min(1380, screen_w - 80), min(920, screen_h - 90)
        self.root.geometry(f"{width}x{height}+30+30")
        self.root.minsize(1020, 720)
        self.root.configure(background="#0a121c")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            ".", background="#0e1925", foreground="#dfeaec", font=("Segoe UI", 10), borderwidth=0
        )
        style.configure("TFrame", background="#0e1925")
        style.configure("Stage.TFrame", background="#0a121c")
        style.configure("TLabel", background="#0e1925", foreground="#dfeaec")
        style.configure("Muted.TLabel", foreground="#91a7b4")
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 23), foreground="#79efc5")
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 10), foreground="#79efc5")
        style.configure(
            "Section.TButton",
            font=("Segoe UI Semibold", 10),
            foreground="#79efc5",
            background="#172a3a",
            anchor="w",
            padding=(8, 7),
        )
        style.map("Section.TButton", background=[("active", "#263b4c")])
        style.configure("Mono.TLabel", font=("Cascadia Mono", 9))
        style.configure("TButton", padding=(12, 8), background="#263b4c")
        style.map(
            "TButton",
            background=[("active", "#3b586c"), ("disabled", "#182735")],
            foreground=[("disabled", "#69808d")],
        )
        style.configure("Accent.TButton", background="#477c70")
        style.map("Accent.TButton", background=[("active", "#579683"), ("disabled", "#263b40")])
        style.configure(
            "TEntry",
            fieldbackground="#172a3a",
            foreground="#eef6f5",
            insertcolor="#eef6f5",
            padding=6,
        )
        style.configure("TCombobox", fieldbackground="#172a3a", foreground="#eef6f5", padding=4)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#172a3a")],
            foreground=[("readonly", "#eef6f5")],
        )
        style.configure("TCheckbutton", background="#0e1925", foreground="#dfeaec", padding=(0, 2))
        style.map("TCheckbutton", background=[("active", "#0e1925")])
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#1b2e40",
            background="#79efc5",
            bordercolor="#1b2e40",
            lightcolor="#79efc5",
            darkcolor="#79efc5",
        )

    def _build(self) -> None:
        shell = ttk.Frame(self.root, padding=18)
        shell.pack(fill="both", expand=True)
        heading = ttk.Frame(shell)
        heading.pack(fill="x", pady=(0, 14))
        ttk.Label(heading, text="TRICKROOM", style="Title.TLabel").pack(side="left")
        ttk.Label(heading, text="  /  THE TRACKING LAB", style="Muted.TLabel").pack(
            side="left",
            padx=(8, 0),
            pady=(9, 0),
        )
        ttk.Label(heading, textvariable=self.mode_label, style="Section.TLabel").pack(
            side="right",
            pady=(9, 0),
        )
        content = ttk.Frame(shell)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.preview_frame = ttk.Frame(content, style="Stage.TFrame")
        self.preview_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        self.preview = ttk.Label(self.preview_frame, background="#0a121c", anchor="center")
        self.preview.pack(fill="both", expand=True)
        self.playback_bar = ttk.Frame(content, padding=(0, 6, 0, 0))
        self.playback_bar.grid(row=1, column=0, sticky="ew", padx=(0, 18))
        self.playback_bar.columnconfigure(1, weight=1)
        self.playback_button = ttk.Button(
            self.playback_bar, text="Pause", width=8, command=self.toggle_playback
        )
        self.playback_button.grid(row=0, column=0, padx=(0, 8))
        self.playback_slider = ttk.Scale(
            self.playback_bar,
            from_=0,
            to=1,
            variable=self.playback_position,
            command=self._preview_seek,
            takefocus=True,
        )
        self.playback_slider.grid(row=0, column=1, sticky="ew")
        self.playback_slider.bind("<ButtonPress-1>", self._drag_playback)
        self.playback_slider.bind("<B1-Motion>", self._drag_playback)
        self.playback_slider.bind("<ButtonRelease-1>", self._commit_seek)
        for key in ("Left", "Right", "Home", "End"):
            self.playback_slider.bind(f"<KeyPress-{key}>", self._step_playback)
            self.playback_slider.bind(f"<KeyRelease-{key}>", self._commit_seek)
        self.playback_slider.bind("<FocusOut>", self._cancel_scrub)
        ttk.Label(
            self.playback_bar, textvariable=self.playback_time, style="Mono.TLabel", width=19
        ).grid(row=0, column=2, padx=(8, 0))
        self.playback_bar.grid_remove()
        side_shell = ttk.Frame(content, width=294)
        side_shell.grid(row=0, column=1, rowspan=2, sticky="ns")
        side_shell.grid_propagate(False)
        self.sections: dict[str, CollapsibleSection] = {}
        section_actions = ttk.Frame(side_shell)
        section_actions.pack(fill="x", pady=(0, 6))
        self.expand_sections_button = ttk.Button(
            section_actions, text="Expand all", command=lambda: self.set_sections_expanded(True)
        )
        self.expand_sections_button.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.collapse_sections_button = ttk.Button(
            section_actions, text="Collapse all", command=lambda: self.set_sections_expanded(False)
        )
        self.collapse_sections_button.pack(side="left", fill="x", expand=True)
        scroll_shell = ttk.Frame(side_shell)
        scroll_shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            scroll_shell, width=294, background="#0e1925", highlightthickness=0, borderwidth=0
        )
        self.controls_canvas = canvas
        scrollbar = ttk.Scrollbar(scroll_shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        panel = ttk.Frame(canvas, width=278)
        canvas.create_window((0, 0), window=panel, anchor="nw", width=276)
        panel.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        section_container = panel

        def section(text: str, *, expanded: bool = False) -> None:
            nonlocal panel
            group = CollapsibleSection(section_container, text, expanded=expanded)
            group.pack(fill="x", pady=(0, 6))
            self.sections[text] = group
            panel = group.body

        section("01 / INPUT", expanded=True)
        ttk.Label(panel, text="IP Webcam URL, device # or video file", style="Muted.TLabel").pack(
            anchor="w",
        )
        self.source_entry = ttk.Entry(panel, textvariable=self.source, show="*")
        self.source_entry.pack(fill="x", pady=5)
        self.source_entry.bind("<Return>", lambda _event: self.connect())
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            panel,
            text="Reveal source (private; never saved)",
            variable=show,
            command=lambda: self.source_entry.configure(
                show="" if show.get() else "*",
            ),
        ).pack(anchor="w")
        auth = ttk.Frame(panel)
        auth.pack(fill="x", pady=(7, 3))
        auth.columnconfigure((0, 1), weight=1)
        ttk.Label(auth, text="Username (optional)", style="Muted.TLabel").grid(row=0, column=0)
        ttk.Label(auth, text="Password", style="Muted.TLabel").grid(row=0, column=1)
        ttk.Entry(auth, textvariable=self.username, width=14).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(0, 6),
        )
        ttk.Entry(auth, textvariable=self.password, show="*", width=14).grid(
            row=1,
            column=1,
            sticky="ew",
        )
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="Rotate input:").pack(side="left")
        ttk.Combobox(
            row,
            textvariable=self.rotation,
            state="readonly",
            width=9,
            values=("none", "left", "right", "180"),
        ).pack(side="right")
        ttk.Checkbutton(
            panel, text="Smooth motion (next connection)", variable=self.smoothing
        ).pack(anchor="w")
        controls = ttk.Frame(panel)
        controls.pack(fill="x", pady=(8, 3))
        self.connect_button = ttk.Button(
            controls, text="Connect", command=self.connect, style="Accent.TButton"
        )
        self.connect_button.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.stop_button = ttk.Button(controls, text="Disconnect", command=self.disconnect)
        self.stop_button.pack(side="right", fill="x", expand=True)
        self.demo_button = ttk.Button(panel, text="Run synthetic demo", command=self.start_demo)
        self.demo_button.pack(fill="x", pady=4)
        ttk.Checkbutton(panel, text="Demo: crop below knees", variable=self.crop_demo).pack(
            anchor="w"
        )
        self.video_button = ttk.Button(
            panel, text="Test from video...", command=self.choose_test_video
        )
        self.video_button.pack(fill="x", pady=(6, 3))
        self.replay_button = ttk.Button(
            panel, text="Replay last video", command=self.replay_test_video, state="disabled"
        )
        self.replay_button.pack(fill="x", pady=3)
        ttk.Label(
            panel,
            text="Video tests drive the synthetic avatar with real detections. "
            "Raw preview stays separately opt-in.",
            style="Muted.TLabel",
            wraplength=270,
        ).pack(fill="x", pady=(2, 4))
        ttk.Label(panel, textvariable=self.message, wraplength=270, style="Muted.TLabel").pack(
            fill="x", pady=(6, 2)
        )
        section("02 / BLENDER MODEL")
        ttk.Label(panel, textvariable=self.model_info, wraplength=270, style="Muted.TLabel").pack(
            fill="x", pady=(0, 5)
        )
        self.load_model_button = ttk.Button(
            panel, text="Load Blender GLB...", command=self.choose_model
        )
        self.load_model_button.pack(fill="x", pady=3)
        ttk.Label(panel, text="Optional mapping profile (.json)", style="Muted.TLabel").pack(
            anchor="w"
        )
        ttk.Entry(panel, textvariable=self.model_profile).pack(fill="x", pady=3)
        ttk.Button(panel, text="Choose mapping profile...", command=self.choose_profile).pack(
            fill="x"
        )
        self.model_modes = ttk.Combobox(
            panel, textvariable=self.model_mode, state="readonly", values=("live", "bind")
        )
        self.model_modes.pack(fill="x", pady=(8, 3))
        self.model_modes.bind("<<ComboboxSelected>>", self.change_model_mode)
        model_actions = ttk.Frame(panel)
        model_actions.pack(fill="x")
        ttk.Button(model_actions, text="Recalibrate", command=self.recalibrate_model).pack(
            side="left", expand=True, fill="x", padx=(0, 4)
        )
        ttk.Button(model_actions, text="Use built-in", command=self.use_builtin).pack(
            side="left", expand=True, fill="x"
        )
        ttk.Button(panel, text="View model report", command=self.show_model_report).pack(
            fill="x", pady=3
        )
        section("03 / RIG MOTION")
        ttk.Checkbutton(panel, text="Enhanced motion (GLB only)", variable=self.rig_motion).pack(
            anchor="w"
        )
        ttk.Label(panel, text="Rig coordinates", style="Muted.TLabel").pack(anchor="w")
        ttk.Combobox(
            panel, textvariable=self.rig_space, state="readonly", values=("world", "image")
        ).pack(fill="x", pady=3)
        ttk.Checkbutton(
            panel, text="Constrain limb bend/twist", variable=self.rig_constraints
        ).pack(anchor="w")
        ttk.Checkbutton(
            panel, text="Relax lost limbs (not tracked)", variable=self.relax_missing
        ).pack(anchor="w")
        ttk.Label(panel, textvariable=self.motion_info, wraplength=270, style="Mono.TLabel").pack(
            fill="x", pady=5
        )
        section("04 / FACE RESPONSE")
        ttk.Checkbutton(panel, text="Shape facial response", variable=self.face_shaping).pack(
            anchor="w"
        )
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=3)
        ttk.Button(
            actions, text="Neutral (1s)", command=lambda: self.calibrate_face("neutral")
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Range (3s)", command=lambda: self.calibrate_face("range")).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(panel, text="Clear face calibration", command=self.clear_face_calibration).pack(
            fill="x", pady=3
        )
        labels = (
            "Left blink",
            "Right blink",
            "Jaw",
            "Smile",
            "Left brow",
            "Right brow",
            "Horizontal gaze",
            "Vertical gaze",
        )
        for name, label in zip(CHANNELS, labels, strict=True):
            row = ttk.Frame(panel)
            row.pack(fill="x")
            ttk.Label(row, text=f"{label} gain", width=19).pack(side="left")
            ttk.Scale(
                row,
                from_=0.25,
                to=3,
                variable=self.face_gains[name],
            ).pack(side="right", fill="x", expand=True)
        ttk.Label(
            panel, textvariable=self.face_response_info, wraplength=270, style="Muted.TLabel"
        ).pack(fill="x", pady=5)
        section("05 / PRESENTATION")
        for text, variable in (
            ("Mirror output (not inference)", self.mirror),
            ("Camera contour (debug)", self.outline),
            ("Skeleton joints (debug)", self.skeleton),
            ("Large head detail", self.detail),
            ("Perspective lab room", self.grid),
        ):
            ttk.Checkbutton(panel, text=text, variable=variable).pack(anchor="w")
        ttk.Button(panel, text="Open clean output window", command=self.open_output).pack(
            fill="x",
            pady=(8, 0),
        )
        section("06 / PRIVATE DEBUG WINDOWS")
        for name, label in (
            ("input", "Raw input camera (private)"),
            ("skeleton", "Detected skeleton on black"),
            ("face", "Detected face mesh on black"),
        ):
            ttk.Checkbutton(
                panel,
                text=label,
                variable=self.debug_options[name],
                command=lambda key=name: self.toggle_debug(key),
            ).pack(anchor="w")
        ttk.Label(
            panel,
            text="Raw input exposes the real feed in its own window. "
            "All debug views start off and never enter clean output.",
            style="Muted.TLabel",
            wraplength=270,
        ).pack(fill="x", pady=5)
        section("07 / TRACKING INPUT")
        for variable in (self.capture_info, self.frame_info, self.body_info, self.face_info):
            ttk.Label(panel, textvariable=variable, style="Mono.TLabel", wraplength=270).pack(
                anchor="w", pady=2
            )
        ttk.Label(panel, textvariable=self.pose_info, style="Mono.TLabel", wraplength=270).pack(
            anchor="w", pady=(4, 6)
        )
        for name, variable in self.meters.items():
            row = ttk.Frame(panel)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=name, width=11).pack(side="left")
            ttk.Progressbar(row, variable=variable, maximum=1, length=155).pack(side="right")
        ttk.Label(
            panel,
            text="Blink bars measure closure. Unavailable face resets the bars.",
            wraplength=270,
            style="Muted.TLabel",
        ).pack(fill="x", pady=6)

        section("08 / GHOST CAMERA")
        ttk.Checkbutton(
            panel,
            text="Fly the view (imported model only)",
            variable=self.ghost_enabled,
            command=self.toggle_ghost_camera,
        ).pack(anchor="w", pady=2)
        ttk.Label(
            panel,
            text=(
                "Click the stage to capture the mouse, then look with the mouse.\n"
                "W/A/S/D move, Q/E or Space/Ctrl rise and fall, Shift is precision.\n"
                "Esc releases the mouse. Tracking is unaffected by where you fly."
            ),
            wraplength=270,
            style="Muted.TLabel",
        ).pack(fill="x", pady=4)
        fov_row = ttk.Frame(panel)
        fov_row.pack(fill="x", pady=3)
        ttk.Label(fov_row, text="Field of view", width=13).pack(side="left")
        ttk.Scale(
            fov_row,
            from_=MIN_FOV,
            to=MAX_FOV,
            variable=self.ghost_fov,
            command=lambda _value: self.apply_ghost_fov(),
        ).pack(side="right", fill="x", expand=True)
        speed_row = ttk.Frame(panel)
        speed_row.pack(fill="x", pady=3)
        ttk.Label(speed_row, text="Speed m/s", width=13).pack(side="left")
        ttk.Scale(speed_row, from_=0.5, to=8.0, variable=self.ghost_speed).pack(
            side="right", fill="x", expand=True
        )
        ttk.Button(panel, text="Reset view", command=self.reset_ghost_camera).pack(
            fill="x", pady=(6, 2)
        )
        ttk.Label(panel, textvariable=self.ghost_info, style="Mono.TLabel", wraplength=270).pack(
            anchor="w", pady=4
        )
        ttk.Label(
            panel,
            text=(
                "The viewpoint is presentation only. It cannot improve a single-camera "
                "pose estimate, so steep angles expose depth error a front view hides."
            ),
            wraplength=270,
            style="Muted.TLabel",
        ).pack(fill="x", pady=4)

        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(
            footer,
            text="SYNTHETIC OUTPUT  /  RAW INPUT DEBUG IS PRIVATE OPT-IN  /  ESC: DISCONNECT",
            style="Mono.TLabel",
        ).pack(side="left")
        ttk.Label(
            footer, text="Built-in + Blender GLB / humanoid profile 1", style="Muted.TLabel"
        ).pack(side="right")

    # --- ghost camera -----------------------------------------------------
    # Input is collected here and handed to the camera as an abstract command.
    # Keeping device handling outside the camera means a focused control simply
    # stops producing movement instead of fighting it.

    MOVE_KEYS = {
        "w": "forward",
        "s": "back",
        "a": "left",
        "d": "right",
        "e": "up",
        "q": "down",
        "space": "up",
        "control_l": "down",
        "control_r": "down",
        "shift_l": "slow",
        "shift_r": "slow",
    }

    def _escape(self, _event=None) -> None:
        """Escape releases the pointer first, and only then disconnects."""
        if self._ghost_captured:
            self.release_pointer()
            return
        self.disconnect()

    def _ghost_active(self) -> bool:
        enabled = getattr(self, "ghost_enabled", None)
        return bool(enabled.get()) if enabled is not None else False

    def _ghost_key_press(self, event) -> None:
        if not self._ghost_active():
            return
        key = (event.keysym or "").lower()
        if key in self.MOVE_KEYS and not isinstance(
            self.root.focus_get(), ttk.Entry | tk.Entry | ttk.Scale
        ):
            self._ghost_keys.add(key)

    def _ghost_key_release(self, event) -> None:
        self._ghost_keys.discard((event.keysym or "").lower())

    def _capture_pointer(self, _event=None) -> None:
        if not self._ghost_active():
            return
        self._ghost_captured = True
        self._ghost_pointer = None
        self.preview_frame.focus_set()
        try:
            self.preview_frame.configure(cursor="none")
        except tk.TclError:
            pass

    def release_pointer(self) -> None:
        self._ghost_captured = False
        self._ghost_pointer = None
        self._ghost_keys.clear()
        self._ghost_look = [0.0, 0.0]
        frame = getattr(self, "preview_frame", None)
        if frame is None:
            return
        try:
            frame.configure(cursor="")
        except tk.TclError:
            pass

    def _ghost_motion(self, event) -> None:
        if not (self._ghost_active() and self._ghost_captured):
            return
        if self._ghost_pointer is not None:
            self._ghost_look[0] += event.x - self._ghost_pointer[0]
            self._ghost_look[1] += event.y - self._ghost_pointer[1]
        self._ghost_pointer = (event.x, event.y)

    def toggle_ghost_camera(self) -> None:
        if not self._ghost_active():
            self.release_pointer()
            self.ghost_info.set("Ghost camera off. The stage view is unchanged.")
            return
        self.ghost_info.set("Click the stage to capture the mouse.")

    def apply_ghost_fov(self) -> None:
        try:
            self.ghost_camera.set_fov(float(self.ghost_fov.get()))
        except ValueError:
            pass

    def reset_ghost_camera(self) -> None:
        self.ghost_camera.reset()
        self.ghost_fov.set(self.ghost_camera.fov_y)
        self.release_pointer()

    def _advance_ghost_camera(self, now: float) -> None:
        # Harnesses build a Studio with only the fields a test needs, so this
        # step must be inert rather than raising when the camera is absent.
        if getattr(self, "ghost_camera", None) is None:
            return
        previous = getattr(self, "_ghost_clock", None)
        self._ghost_clock = now
        if not self._ghost_active():
            return
        held = self._ghost_keys
        command = CameraCommand(
            forward=("w" in held) - ("s" in held),
            side=("d" in held) - ("a" in held),
            up=(("e" in held) or ("space" in held)) - (("q" in held) or ("control_l" in held)),
            yaw_delta=self._ghost_look[0],
            pitch_delta=self._ghost_look[1],
            slow=("shift_l" in held) or ("shift_r" in held),
        )
        self._ghost_look = [0.0, 0.0]
        speed = float(self.ghost_speed.get())
        if speed > 0:
            self.ghost_camera.speed = speed
        self.ghost_camera.update(command, now - previous if previous is not None else 0.0)
        pose = self.ghost_camera.pose()
        x, y, z = pose["position"]
        self.ghost_info.set(
            f"x {x:+.2f}  y {y:+.2f}  z {z:+.2f}\n"
            f"yaw {pose['yaw']:+.1f}  pitch {pose['pitch']:+.1f}  fov {pose['fov']:.0f}\n"
            + ("MOUSE CAPTURED / Esc releases" if self._ghost_captured else "Click stage for mouse")
        )

    def set_sections_expanded(self, expanded: bool) -> None:
        for section in self.sections.values():
            section.set_expanded(expanded)
        if not expanded:
            self.controls_canvas.yview_moveto(0)

    def choose_profile(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Select TrickRoom mapping profile",
            filetypes=(("JSON mapping", "*.json"),),
        )
        if path:
            self.model_profile.set(path)

    def choose_model(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Import Blender-exported GLB",
            filetypes=(("glTF binary model", "*.glb"),),
        )
        if path:
            profile = Path(self.model_profile.get()) if self.model_profile.get().strip() else None
            self.load_model(Path(path), profile)

    def load_model(self, path: Path, profile: Path | None = None, mode: str = "live") -> None:
        if self._closing or self._model_pending:
            return
        self.load_model_button.configure(state="disabled")
        self._model_pending = True
        self._model_generation += 1
        generation = self._model_generation
        self.model_info.set("Validating model... current avatar remains available.")

        def worker():
            try:
                sidecar = path.with_suffix(".trickroom.json")
                selected = profile or (sidecar if sidecar.is_file() else None)
                asset = load_asset(path, selected)
                instance = AvatarInstance(asset)
                instance.set_mode(mode, time.perf_counter())
                self._model_results.put((generation, instance, asset.report(), None))
            except (AssetError, OSError) as error:
                self._model_results.put((generation, None, None, str(error)))

        self._model_thread = threading.Thread(
            target=worker, name="trickroom-model-loader", daemon=True
        )
        self._model_thread.start()

    def _poll_model(self) -> None:
        if self._model_commit is not None:
            future, instance, report = self._model_commit
            if not future.done():
                return
            future.result()
            self._model_commit = None
            self._finish_model(instance, report)
            return
        try:
            generation, instance, report, error = self._model_results.get_nowait()
        except queue.Empty:
            if (
                self._model_pending
                and self._model_thread is not None
                and not self._model_thread.is_alive()
            ):
                self._model_pending = False
                self.load_model_button.configure(state="normal")
                self.model_info.set(
                    "Loader ended unexpectedly; previous avatar retained. See terminal."
                )
            return
        if generation != self._model_generation or self._closing:
            self._model_pending = False
            return
        if error:
            self._model_pending = False
            self.load_model_button.configure(state="normal")
            self.model_info.set("Import rejected: " + error)
            return
        future = self._render_command(lambda: self.renderer.set_model(instance))
        self._model_commit = (future, instance, report)

    def _finish_model(self, instance: AvatarInstance, report: dict) -> None:
        self._model_pending = False
        self.load_model_button.configure(state="normal")
        self._model_report = report
        self.model_mode.set(instance.mode)
        self.model_modes.configure(values=("live", "bind", *(c.name for c in instance.asset.clips)))
        warning = (
            f"\n{len(report['warnings'])} warning(s); view report." if report["warnings"] else ""
        )
        self.model_info.set(
            f"{report['name']}\n{report['triangles']} triangles / "
            f"{len(report['bones'])} mapped bones"
            f"\n{len(report['shapes'])} shape keys / {len(report['clips'])} clips{warning}"
        )

    def use_builtin(self) -> None:
        if self._model_pending:
            self.model_info.set("Wait for model validation to finish before switching.")
            return
        self._render_command(self.renderer.use_builtin)
        self._model_generation += 1
        self._model_pending = False
        self.load_model_button.configure(state="normal")
        self._model_report = None
        self.model_mode.set("live")
        self.model_modes.configure(values=("live", "bind"))
        self.model_info.set("Built-in reference character")

    def change_model_mode(self, _event=None) -> None:
        if self._model_pending:
            return
        if self._model_report is None:
            self.model_mode.set("live")
            self.model_info.set("Load a GLB to use bind-pose or clip previews.")
            return
        mode, now = self.model_mode.get(), time.perf_counter()
        self._render_command(lambda: self.renderer.imported.set_mode(mode, now))

    def recalibrate_model(self) -> None:
        if self._model_report is not None and not self._model_pending:
            self._render_command(lambda: self.renderer.imported.reset_calibration())
            self.message.set("Scale smoothing reset. Model size follows the current pose framing.")

    def calibrate_face(self, kind: str) -> None:
        state = self.runtime.observation if self.runtime is not None else None
        now = time.perf_counter()
        if (
            self.demo
            or state is None
            or state.face is None
            or state.age(now) > 0.6
            or self.runtime.status.state == "PAUSED"
        ):
            self.message.set("Face calibration requires a fresh camera/replay detection, not demo.")
            return
        if kind == "range" and not self.render_worker.status.face_calibrated:
            self.message.set("Calibrate a neutral face before capturing expression range.")
            return
        if kind not in ("neutral", "range"):
            self.message.set("Choose neutral or range face calibration.")
            return
        self._render_command(lambda: self.renderer.face_response.begin(kind, now))
        self.face_shaping.set(True)
        self.message.set("Starting session-only face calibration...")

    def clear_face_calibration(self) -> None:
        def clear():
            self.renderer.face_response.reset()
            self.renderer.face_response.enabled = False

        self._render_command(clear)
        self.face_shaping.set(False)
        self.message.set("Face calibration cleared; no personal values were saved.")

    def show_model_report(self) -> None:
        if self._model_report is None:
            self.model_info.set("Load a prepared GLB to inspect its bone, shape and clip report.")
            return
        window = tk.Toplevel(self.root)
        window.title("TrickRoom - Imported model report")
        text = ScrolledText(
            window,
            width=86,
            height=30,
            background="#0e1925",
            foreground="#dfeaec",
            font=("Cascadia Mono", 10),
        )
        text.pack(fill="both", expand=True)
        text.insert("1.0", json.dumps(self._model_report, indent=2))
        text.configure(state="disabled")

    def _can_change_source(self) -> bool:
        if self._closing:
            return False
        if self._disconnecting or (self.runtime is not None and self.runtime.alive):
            self.message.set("Disconnect and wait for shutdown before changing the source.")
            return False
        return True

    def choose_test_video(self) -> None:
        if not self._can_change_source():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a recording for the synthetic test view",
            filetypes=(
                ("Video recordings", "*.mp4 *.avi *.mov *.mkv *.webm *.m4v"),
                ("All files", "*.*"),
            ),
        )
        if path:
            self.play_test_video(Path(path))

    def play_test_video(self, path: Path) -> None:
        if not self._can_change_source():
            return
        if self._model_pending:
            self.message.set("Wait for model loading to finish before starting a video test.")
            return
        try:
            source = Source.parse(str(path))
            if source.kind != "file":
                raise ValueError("Choose an existing video file, not a camera or network source.")
        except (ValueError, OSError):
            self.message.set("Video test could not start. Choose an existing readable video file.")
            return
        self.source.set(str(source.location))
        if self._model_report is not None:
            self.model_mode.set("live")
            now = time.perf_counter()
            self._render_command(lambda: self.renderer.imported.set_mode("live", now))
        self._start_source(source)

    def replay_test_video(self) -> None:
        if self._test_video is None:
            self.message.set("Choose a recording with Test from video first.")
            return
        self.play_test_video(self._test_video)

    def connect(self) -> None:
        if not self._can_change_source():
            return
        try:
            source = Source.parse(self.source.get(), self.username.get(), self.password.get())
        except ValueError as error:
            self.message.set(str(error))
            return
        self._start_source(source)

    def _start_source(
        self,
        source: Source,
        *,
        start_position: float = 0.0,
        paused: bool = False,
        preserve_face_calibration: bool = False,
    ) -> None:
        if source.kind == "file":
            self._test_video = Path(source.location)
        if preserve_face_calibration:
            self._reset_seek_presentation()
        else:
            self._render_command(self.renderer.reset_motion)
        self._scrubbing = False
        self._pending_seek = None
        self._requested_paused = paused
        self.demo = False
        self.runtime = Runtime(
            source,
            self.models,
            self.rotation.get(),
            self.tracking_size,
            self.smoothing.get(),
            start_position=start_position,
            paused=paused,
        )
        self.runtime.enable_input_preview(self.debug_options["input"].get())
        try:
            self.runtime.start()
        except (OSError, RuntimeError):
            self.mode_label.set("ERROR / SYNTHETIC OUTPUT ONLY")
            self.message.set(self.runtime.status.message)
            self._connection_buttons(True)
            return
        self.mode_label.set(
            "VIDEO REPLAY / LOADING" if source.kind == "file" else "LIVE INPUT / LOADING"
        )
        self.message.set(
            "Loading video test. No live camera is opened; output stays synthetic."
            if source.kind == "file"
            else "Loading local models. Camera pixels remain private."
        )
        self._connection_buttons(False)

    def _reset_seek_presentation(self) -> None:
        self._render_command(lambda: self.renderer.reset_motion(preserve_face_calibration=True))
        self._debug_photos.clear()
        for _window, label in self._debug_windows.values():
            label.configure(image="")

    def _playback_available(self) -> bool:
        return (
            self.runtime is not None
            and self.runtime.camera.source.kind == "file"
            and not self._closing
            and not self._disconnecting
            and self.runtime.status.state in ("RUNNING", "PAUSED", "ENDED")
            and (self.runtime.status.state != "ENDED" or not self.runtime.alive)
        )

    def toggle_playback(self) -> None:
        if not self._playback_available():
            return
        if self.runtime.status.state == "ENDED":
            self._start_source(self.runtime.camera.source, preserve_face_calibration=True)
            return
        try:
            paused = (
                self._requested_paused
                if self._requested_paused is not None
                else self.runtime.camera.status.paused
            )
            self.runtime.set_paused(not paused)
            self._requested_paused = not paused
            if not paused:
                self._render_command(self._pause_face_calibration)
        except (ValueError, RuntimeError) as error:
            self.message.set(str(error))

    def seek_playback(self, seconds: float) -> None:
        if not self._playback_available():
            return
        capture = self.runtime.camera.status
        if (
            not math.isfinite(seconds)
            or capture.duration_seconds <= 0
            or not 0 <= seconds <= capture.duration_seconds
        ):
            self.message.set("Select a position inside the recording timeline.")
            return
        try:
            if self.runtime.status.state == "ENDED":
                self._start_source(
                    self.runtime.camera.source,
                    start_position=seconds,
                    preserve_face_calibration=True,
                )
            else:
                self.runtime.seek(seconds)
                self._pending_seek = seconds
                self._reset_seek_presentation()
        except (ValueError, RuntimeError) as error:
            self.message.set(str(error))

    def _preview_seek(self, _value=None) -> None:
        if self._scrubbing and self.runtime is not None:
            label = (
                f"{format_replay_time(self.playback_position.get())} / "
                f"{format_replay_time(self.runtime.camera.status.duration_seconds)}"
            )
            if self.playback_time.get() != label:
                self.playback_time.set(label)

    def _drag_playback(self, event) -> str:
        if not self.playback_slider.instate(["disabled"]):
            if not self._scrubbing:
                self.playback_slider.focus_set()
            self._scrubbing = True
            self.playback_position.set(float(self.playback_slider.get(event.x, event.y)))
            self._preview_seek()
        return "break"

    def _commit_seek(self, _event=None) -> str:
        scrubbing = self._scrubbing
        self._scrubbing = False
        if scrubbing and not self.playback_slider.instate(["disabled"]):
            self.seek_playback(self.playback_position.get())
        return "break"

    def _step_playback(self, event) -> str:
        if not self.playback_slider.instate(["disabled"]):
            duration = self.runtime.camera.status.duration_seconds
            position = self.playback_position.get()
            targets = {"Left": position - 1, "Right": position + 1, "Home": 0.0, "End": duration}
            self._scrubbing = True
            self.playback_position.set(max(0.0, min(duration, targets[event.keysym])))
            self._preview_seek()
        return "break"

    def _cancel_scrub(self, _event=None) -> None:
        self._scrubbing = False

    def _update_playback(self) -> None:
        visible = (
            self.runtime is not None
            and self.runtime.camera.source.kind == "file"
            and not self._disconnecting
            and not self.demo
        )
        if visible != self._timeline_visible:
            self._timeline_visible = visible
            if visible:
                self.playback_bar.grid()
            else:
                self.playback_bar.grid_remove()
                self._scrubbing = False
        if not visible:
            self._pending_seek = self._requested_paused = None
            self._playback_config = None
            return
        capture, status = self.runtime.camera.status, self.runtime.status
        if self._pending_seek is not None:
            if status.state == "ENDED" and not self.runtime.alive:
                self._start_source(
                    self.runtime.camera.source,
                    start_position=self._pending_seek,
                    paused=(
                        self._requested_paused
                        if self._requested_paused is not None
                        else capture.paused
                    ),
                    preserve_face_calibration=True,
                )
                return
            if self.runtime.observation is not None or status.state in ("ERROR", "STOPPED"):
                self._pending_seek = None
        if self._requested_paused == capture.paused:
            self._requested_paused = None
        paused = self._requested_paused if self._requested_paused is not None else capture.paused
        available = self._playback_available()
        duration = capture.duration_seconds
        config = ("Play" if paused or status.state == "ENDED" else "Pause", available, duration)
        if config != self._playback_config:
            self.playback_button.configure(
                text=config[0], state="normal" if available else "disabled"
            )
            self.playback_slider.configure(to=duration if duration > 0 else 1)
            self.playback_slider.state(
                ["!disabled"] if available and duration > 0 else ["disabled"]
            )
            self._playback_config = config
        if not self._scrubbing:
            state = self.runtime.observation
            position = (
                state.media_time
                if state is not None
                and state.media_time is not None
                and capture.state != "SEEKING"
                and status.state != "ENDED"
                else capture.position_seconds
            )
            self.playback_position.set(min(position, duration) if duration > 0 else 0)
            total = format_replay_time(duration) if duration > 0 else "--:--"
            self.playback_time.set(f"{format_replay_time(position)} / {total}")

    def _connection_buttons(self, idle: bool) -> None:
        self.connect_button.configure(state="normal" if idle else "disabled")
        self.demo_button.configure(state="normal" if idle else "disabled")
        self.video_button.configure(state="normal" if idle else "disabled")
        self.replay_button.configure(
            state="normal" if idle and self._test_video is not None else "disabled"
        )

    def disconnect(self) -> None:
        self._clear_debug_frames()
        self._render_command(self.renderer.reset_motion)
        if self.runtime is not None and self.runtime.alive:
            self.runtime.stop()
            self._disconnecting = True
            self.message.set("Stopping capture and inference...")
        else:
            self.runtime = None
            self.message.set("Disconnected. No camera is active.")
            self._connection_buttons(True)
        self.demo = False

    def start_demo(self) -> None:
        if self.runtime is not None and self.runtime.alive:
            self.message.set("Disconnect before entering the synthetic demo.")
            return
        self.runtime = None
        self._clear_debug_frames()
        self._render_command(self.renderer.reset_motion)
        self.demo = True
        self._demo_start = time.perf_counter()
        self._connection_buttons(True)
        self.message.set("Scripted body/face motion, not camera tracking. No camera is open.")

    def open_output(self) -> None:
        if self._output_window is not None and self._output_window.winfo_exists():
            self._output_window.lift()
            return
        window = tk.Toplevel(self.root)
        window.title("TrickRoom - Synthetic Output")
        window.geometry("960x720")
        window.minsize(320, 240)
        window.configure(background="#0a121c")
        self._output_window = window
        self._output_label = ttk.Label(window, background="#0a121c", anchor="center")
        self._output_label.pack(fill="both", expand=True)

    def toggle_debug(self, name: str) -> None:
        if name not in self.debug_options:
            raise ValueError("Unknown debug view.")
        enabled = self.debug_options[name].get()
        if name == "input" and self.runtime is not None:
            self.runtime.enable_input_preview(enabled)
        if not enabled:
            pair = self._debug_windows.pop(name, None)
            self._debug_photos.pop(name, None)
            if pair is not None:
                pair[0].destroy()
            return
        if name in self._debug_windows:
            self._debug_windows[name][0].lift()
            return
        window = tk.Toplevel(self.root)
        window.title(debug_views.TITLES[name])
        window.geometry("720x720" if name != "input" else "960x720")
        window.minsize(320, 240)
        window.configure(background="black")
        label = ttk.Label(window, background="black", anchor="center")
        label.pack(fill="both", expand=True)
        self._debug_windows[name] = (window, label)

        def close_view():
            self.debug_options[name].set(False)
            self.toggle_debug(name)

        window.protocol("WM_DELETE_WINDOW", close_view)
        self._view_due[name] = 0.0

    def _clear_debug_frames(self) -> None:
        if self.runtime is not None:
            self.runtime.enable_input_preview(False)
        for name, (_window, label) in self._debug_windows.items():
            label.configure(image="")
            self._debug_photos.pop(name, None)

    def _draw_debug(self, name: str, now: float) -> None:
        state, raw = (
            self.runtime.debug_snapshot
            if self.runtime is not None and not self._disconnecting
            else (None, None)
        )
        connection = self.runtime.status.state if self.runtime is not None else "READY"
        paused = connection == "PAUSED"
        window, label = self._debug_windows[name]
        size = (
            max(320, min(1920, window.winfo_width())),
            max(240, min(1440, window.winfo_height())),
        )
        if name == "input":
            frame = debug_views.raw_input(raw, size, now)
        else:
            draw = debug_views.skeleton if name == "skeleton" else debug_views.face_mesh

            def numeric_view():
                frame = draw(state, size, now, paused=paused)
                return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            self._queue_draw(name, numeric_view, state, now, False, connection)
            return
        photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        self._debug_photos[name] = photo
        label.configure(image=photo)

    def _observation(self, now: float) -> Observation | None:
        if self.demo:
            return demo_observation(now - self._demo_start, now, cropped=self.crop_demo.get())
        if self.runtime is not None and not self._disconnecting:
            return self.runtime.observation
        return None

    def _render_command(self, action):
        self._render_epoch += 1
        future = self.render_worker.submit(action)
        self._render_commands.append(future)
        return future

    def _pause_face_calibration(self) -> None:
        response = self.renderer.face_response
        if response.collecting is not None:
            response.apply(None, time.perf_counter())
            response.message = "Calibration cancelled: replay paused. Resume and retry."

    def _graphics_failed(self, error: Exception) -> None:
        print(f"TrickRoom: graphics failed ({type(error).__name__}); closing safely.")
        self.exit_code = 2
        self.preview.configure(image="")
        if self._output_label is not None and self._output_label.winfo_exists():
            self._output_label.configure(image="")
        self.close()
        if self._tick_id is not None:
            self.root.after_cancel(self._tick_id)
        self._tick_id = self.root.after(0, self._tick)

    def _clear_view_image(self, name: str) -> None:
        self._displayed.pop(name, None)
        if name == "preview":
            self.preview.configure(image="")
        elif name == "output":
            if self._output_label is not None and self._output_label.winfo_exists():
                self._output_label.configure(image="")
        elif name in self._debug_windows:
            self._debug_windows[name][1].configure(image="")
            self._debug_photos.pop(name, None)

    def _expire_displayed(self, now: float) -> None:
        for name, (runtime, generation, state, connection, preview, epoch) in tuple(
            self._displayed.items()
        ):
            invalid = (
                epoch != self._render_epoch or runtime is not self.runtime or self._disconnecting
            )
            if runtime is not None and not preview:
                invalid |= runtime.camera.status.generation != generation
                invalid |= runtime.status.state in ("ERROR", "STOPPED")
            frozen = (
                runtime is not None
                and connection == "PAUSED"
                and runtime.status.state == "PAUSED"
                and runtime.camera.source.kind == "file"
                and state is not None
                and state.media_time is not None
            )
            if state is not None and not preview and not frozen:
                invalid |= state.age(now) > 0.6
            if invalid:
                self._clear_view_image(name)

    def _queue_draw(self, name, action, state, now, preview_mode, connection):
        runtime = self.runtime
        self._draw_pending = (
            self.render_worker.submit(action),
            name,
            self._render_epoch,
            runtime,
            runtime.camera.status.generation if runtime is not None else 0,
            state,
            connection,
            now,
            preview_mode,
        )

    def _publish_draw(self) -> bool:
        if self._draw_pending is None:
            return False
        future, name, epoch, runtime, generation, state, connection, started, preview_mode = (
            self._draw_pending
        )
        if not future.done():
            if time.perf_counter() - started > 5:
                raise TimeoutError("The graphics worker did not finish its frame.")
            return False
        self._draw_pending = None
        image = future.result()
        if epoch != self._render_epoch or runtime is not self.runtime or self._disconnecting:
            return True
        if runtime is not None and (
            runtime.camera.status.generation != generation or runtime.status.state != connection
        ):
            return True
        frozen = (
            runtime is not None
            and runtime.camera.source.kind == "file"
            and connection == "PAUSED"
            and state is not None
            and state.media_time is not None
        )
        if (
            state is not None
            and not frozen
            and not preview_mode
            and state.age(time.perf_counter()) > 0.6
        ):
            self._clear_view_image(name)
            return True
        photo = ImageTk.PhotoImage(image)
        self._displayed[name] = (runtime, generation, state, connection, preview_mode, epoch)
        if name == "preview":
            self._photo = photo
            self.preview.configure(image=photo)
            now = time.perf_counter()
            if self._last_tick:
                self._render_fps = 1.0 / max(now - self._last_tick, 0.001)
            self._last_tick = now
        elif (
            name == "output"
            and self._output_window is not None
            and self._output_window.winfo_exists()
        ):
            self._output_photo = photo
            self._output_label.configure(image=photo)
        elif name in self._debug_windows:
            self._debug_photos[name] = photo
            self._debug_windows[name][1].configure(image=photo)
        return True

    def _render_tick(self) -> None:
        if self._closing:
            return
        try:
            if self._publish_draw():
                self._render_tick_id = self.root.after(8, self._render_tick)
                return
        except Exception as error:
            self._graphics_failed(error)
            return
        now = time.perf_counter()
        active = ["input"] if "input" in self._debug_windows else []
        if self._draw_pending is None:
            active.extend(name for name in self._debug_windows if name != "input")
            active.append("preview")
            if self._output_window is not None and self._output_window.winfo_exists():
                active.append("output")
        if not active:
            self._render_tick_id = self.root.after(8, self._render_tick)
            return
        name = min(active, key=self._view_due.__getitem__)
        if self._view_due[name] <= now:
            if name in ("preview", "output"):
                self._draw_avatar(name, now)
                rate = 60 if self.rig_motion.get() and self.render_worker.status.imported else 30
            else:
                self._draw_debug(name, now)
                rate = 15
            self._view_due[name] = now + 1 / rate
        due = min(self._view_due[name] for name in active)
        delay = max(8, round((due - time.perf_counter()) * 1000))
        self._render_tick_id = self.root.after(delay, self._render_tick)

    def _tick(self) -> None:
        now = time.perf_counter()
        self._advance_ghost_camera(now)
        if self._closing:
            if self.render_worker.error is not None:
                self.exit_code = 2
            if self.runtime is not None and self.runtime.status.forced_shutdown:
                self.exit_code = 2
            loading = (
                self._model_thread is not None and self._model_thread.is_alive()
            ) or self.render_worker.alive
            if (self.runtime is None or not self.runtime.alive) and not loading:
                self.root.destroy()
            elif now - self._shutdown_started > 6.0:
                print(
                    "TrickRoom: capture, model loading or graphics exceeded the shutdown deadline."
                )
                self.exit_code = 2
                self.root.destroy()
            else:
                self.root.after(80, self._tick)
            return
        try:
            if not self.render_worker.alive:
                raise RuntimeError("The graphics worker exited unexpectedly.")
            pending = []
            for future in self._render_commands:
                if future.done():
                    future.result()
                else:
                    pending.append(future)
            self._render_commands = pending
            self._poll_model()
        except Exception as error:
            self._graphics_failed(error)
            return
        if self._disconnecting and (self.runtime is None or not self.runtime.alive):
            forced = self.runtime is not None and self.runtime.status.forced_shutdown
            self.runtime = None
            self._disconnecting = False
            self._connection_buttons(True)
            self.message.set(
                "Worker required forced shutdown. No camera is active; see terminal."
                if forced
                else "Disconnected. No camera is active."
            )
        self._update_playback()
        self._expire_displayed(now)
        if now - self._last_telemetry > 0.2:
            self._update_telemetry(self._observation(now), now)
            self._last_telemetry = now
        self._tick_id = self.root.after(16, self._tick)

    def _draw_avatar(self, name: str, now: float) -> None:
        state = self._observation(now)
        status = self.runtime.status if self.runtime is not None else None
        connection = status.state if status else "READY"
        replay = self.runtime is not None and self.runtime.camera.source.kind == "file"
        motion = MotionOptions(
            enabled=self.rig_motion.get(),
            space=self.rig_space.get(),
            relax_missing=self.relax_missing.get(),
            constrain_limbs=self.rig_constraints.get(),
        )
        face_enabled = self.face_shaping.get()
        gains = tuple(variable.get() for variable in self.face_gains.values())
        preview = name == "preview"
        options = StageOptions(
            self.mirror.get(),
            self.outline.get(),
            self.skeleton.get(),
            self.grid.get(),
            self.detail.get() if preview else False,
            preview,
        )
        window = self.preview_frame if preview else self._output_window
        w = max(320, min(2560, window.winfo_width()))
        h = max(240, min(1600, window.winfo_height()))
        demo = self.demo
        renderer = self.renderer

        ghost = self.ghost_camera if self.ghost_enabled.get() else None

        def draw():
            renderer.motion_options = motion
            renderer.face_response.enabled = face_enabled
            for channel, gain in zip(CHANNELS, gains, strict=True):
                index = CHANNELS.index(channel)
                if renderer.face_response.gains[index] != gain:
                    renderer.face_response.set_gain(channel, gain)
            if ghost is not None and renderer.imported is not None and state is not None:
                frame = camera_room(ghost, w, h).pixels.copy()
                evaluation = renderer.imported.evaluate(state, now)
                batches = camera_batches(renderer.imported, evaluation, ghost, w, h)
                if batches:
                    draw_textured(frame, batches)
                return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            image = renderer.render(
                state,
                (w, h),
                now=now,
                options=options,
                demo=demo,
                replay=replay,
                connection=connection,
            )
            return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

        self._queue_draw(name, draw, state, now, self.render_worker.status.preview, connection)

    def _update_telemetry(self, state, now: float) -> None:
        graphics = self.render_worker.status
        self.face_response_info.set(graphics.face_message)
        frame = graphics.frame
        if not graphics.imported:
            self.motion_info.set("Built-in: measured parts. Rig controls apply to imported GLBs.")
        elif graphics.preview:
            self.motion_info.set("Bind/clip preview: live rig controls inactive.")
        elif not self.rig_motion.get():
            self.motion_info.set("Legacy image-space rig; strict missing-part visibility.")
        elif frame is not None and frame.evaluation.tracking_states is not None:
            counts = Counter(frame.evaluation.tracking_states.values())
            self.motion_info.set(
                f"{self.rig_space.get().upper()} rig / "
                + "  ".join(f"{name}:{count}" for name, count in sorted(counts.items()))
                + "\nHeld/rest poses are not detections."
            )
        else:
            self.motion_info.set("Rig waiting for fresh tracking.")
        if self.demo:
            self.mode_label.set("DEMO / no camera access")
            self.capture_info.set(f"Scripted demo / Display {self._render_fps:.0f}/s")
            self.frame_info.set("Not a live tracking measurement")
        elif self.runtime is not None:
            status, capture = self.runtime.status, self.runtime.camera.status
            replay = self.runtime.camera.source.kind == "file"
            input_label = "VIDEO REPLAY" if replay else "LIVE INPUT"
            self.mode_label.set(f"{input_label} / {capture.state}")
            if status.state == "ERROR":
                self.mode_label.set("ERROR / SYNTHETIC OUTPUT ONLY")
                self.message.set(status.message)
                if not self.runtime.alive:
                    self._connection_buttons(True)
            elif status.state == "ENDED":
                self.mode_label.set("REPLAY ENDED")
                self.message.set("Replay finished. Seek on the timeline or press Play to restart.")
                if not self.runtime.alive:
                    self._connection_buttons(True)
            elif status.state == "PAUSED":
                self.mode_label.set("VIDEO REPLAY / PAUSED")
                self.message.set("Replay paused. Drag the timeline to inspect another position.")
            elif capture.message:
                self.message.set(capture.message)
            elif capture.state == "STREAMING":
                self.message.set(
                    "Video replay drives the synthetic view. No live camera or recording is active."
                    if replay
                    else "One performer. Keep face and limbs visible; no recording is active."
                )
            rate_label = "Replay" if replay else "Capture"
            self.capture_info.set(
                "Replay paused / no new inference"
                if status.state == "PAUSED"
                else f"{rate_label} {capture.fps:.1f}/s / Track {status.fps:.1f}/s"
            )
            self.frame_info.set(
                f"{capture.size[0]}x{capture.size[1]} / skipped {status.dropped}\n"
                + (f"Observation age {state.age(now) * 1000:.0f} ms" if state else "Acquiring...")
            )
        else:
            self.mode_label.set("READY / NO CAMERA")
            self.capture_info.set("Capture -- / Inference --")
            self.frame_info.set("No input frames")
        paused = self.runtime is not None and self.runtime.status.state == "PAUSED"
        sample_time = state.completed_at if paused and state is not None else now
        fresh = state is not None and state.age(sample_time) <= 0.6
        body = state.body_status(sample_time) if state else "WAITING"
        count = state.visible_joints if fresh else 0
        prefix = "DEMO / " if self.demo else "PAUSED SAMPLE / " if paused else ""
        self.body_info.set(f"Body: {prefix}{body} ({count}/33)")
        face = state.face if fresh else None
        self.face_info.set(
            "Face: DEMO (scripted)"
            if self.demo
            else "Face: PAUSED SAMPLE"
            if paused and face
            else "Face: TRACKED (head crop)"
            if face and face.crop_used
            else "Face: TRACKED"
            if face
            else "Face: UNAVAILABLE / pose head only"
        )
        if face:
            self.pose_info.set(
                f"Pitch {face.pitch:+.0f}  Yaw {face.yaw:+.0f}  Roll {face.roll:+.0f}"
            )
            ex = face.expression
            values = (ex.blink_left, ex.blink_right, ex.jaw_open, ex.smile)
        else:
            self.pose_info.set("Pitch --   Yaw --   Roll --")
            values = (0.0,) * 4
        for variable, value in zip(self.meters.values(), values, strict=True):
            variable.set(value)
        if graphics.preview:
            self.mode_label.set("MODEL PREVIEW / " + graphics.mode)

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.render_worker.close()
        if self._render_tick_id is not None:
            self.root.after_cancel(self._render_tick_id)
            self._render_tick_id = None
        self._shutdown_started = time.perf_counter()
        self.demo = False
        self._clear_debug_frames()
        if self.runtime is not None:
            self.runtime.stop()
            self.message.set("Closing camera and inference; please wait...")
