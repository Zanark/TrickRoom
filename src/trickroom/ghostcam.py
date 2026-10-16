"""A free-fly ghost camera that views the stage without taking part in it.

The capture camera supplies pose data. This camera only decides where that pose
is observed from, so a shot can be reframed without touching tracking. The
separation follows replay-system practice: a demo records authoritative world
state and the view is a reconstructable projection over it, never part of it.
Quake writes recorded view angles beside the network message rather than inside
it, and Valve implements spectator roaming as noclip movement layered over an
unchanged simulation.

Conventions follow trickroom.room: metres, +X right, +Y up, +Z away from the
viewer, with the floor at y=0. That is deliberately not the OpenGL default of
looking down -Z. The room already projects with ``x / z`` for positive depth,
and matching it keeps one convention in the project instead of two. The
projection below is written for that handedness; do not paste a gluPerspective
matrix over it without re-deriving the signs.

Design decisions taken from that prior art, with the reasons kept visible:

- Modes are symbolic. Valve's own enum shifted ROAMING from 6 to 7 when a mode
  was inserted mid-list, so integers are not portable between versions.
- Ghost movement is noclip: position integrates as ``pos += velocity * dt`` with
  no gravity, friction or collision. A camera has no body to collide with.
- Forward and right come from the full look vector, so flying while pitched
  descends, but vertical input stays world-up. That hybrid is what keeps a free
  camera controllable rather than disorienting.
- The desired velocity is clamped before acceleration. Clamping afterwards
  distorts diagonal movement.
- The slow modifier halves speed for precision framing. It is not a sprint.
- Roll is held at zero while flying. Uncommanded roll removes the horizon that
  a pilot navigates by; it belongs to explicit cinematic work.
- Input arrives as an abstract command rather than being read from a device, so
  exactly one owner drives the camera and a focused control simply stops
  producing commands instead of fighting it.

This camera changes the viewpoint only. It cannot improve a monocular pose
estimate, and viewing a single-camera subject from a steep angle will expose
depth error that a front view hides.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

FREE = "free"
ORBIT = "orbit"
ATTACHED = "attached"
MODES = (FREE, ORBIT, ATTACHED)

MAX_PITCH = 89.0
DEGREES_PER_COUNT = 0.066
MIN_FOV = 20.0
MAX_FOV = 120.0


@dataclass(frozen=True)
class CameraCommand:
    """One frame of abstract input. Devices and key bindings stay outside."""

    forward: float = 0.0
    side: float = 0.0
    up: float = 0.0
    yaw_delta: float = 0.0
    pitch_delta: float = 0.0
    slow: bool = False

    def __post_init__(self) -> None:
        values = (self.forward, self.side, self.up, self.yaw_delta, self.pitch_delta)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Camera command axes must be finite.")
        for name in ("forward", "side", "up"):
            if not -1.0 <= getattr(self, name) <= 1.0:
                raise ValueError("Camera movement axes must lie within -1..1.")


def clamp_pitch(pitch: float, limit: float = MAX_PITCH) -> float:
    """Keep the look vector away from straight up or down.

    Two separate failures meet at +/-90 degrees: the horizontal component of the
    look direction vanishes so yaw is no longer recoverable from it, and the
    Euler decomposition itself loses a degree of freedom. Clamping just short of
    the pole avoids both. The limit is 89 degrees rather than the tighter
    gameplay clamps engines use for a player, because a camera has to be able to
    look very nearly straight down.
    """
    if not math.isfinite(pitch):
        raise ValueError("Pitch must be finite.")
    return max(-limit, min(limit, pitch))


def wrap_yaw(yaw: float) -> float:
    """Keep yaw in -180..180 so interpolation takes the shortest arc."""
    if not math.isfinite(yaw):
        raise ValueError("Yaw must be finite.")
    return (yaw + 180.0) % 360.0 - 180.0


def basis(yaw: float, pitch: float) -> tuple[NDArray[np.float64], ...]:
    """Forward, right and up unit vectors for a yaw/pitch orientation."""
    y, p = math.radians(yaw), math.radians(pitch)
    forward = np.array(
        (math.sin(y) * math.cos(p), math.sin(p), math.cos(y) * math.cos(p)), dtype=float
    )
    right = np.array((math.cos(y), 0.0, -math.sin(y)), dtype=float)
    return forward, right, np.cross(forward, right)


def view_matrix(position, yaw: float, pitch: float) -> NDArray[np.float64]:
    """World-to-camera matrix built from the yaw/pitch basis."""
    forward, right, up = basis(yaw, pitch)
    origin = np.asarray(position, dtype=float).reshape(3)
    if not np.isfinite(origin).all():
        raise ValueError("Camera position must be finite.")
    matrix = np.eye(4)
    matrix[0, :3], matrix[1, :3], matrix[2, :3] = right, up, forward
    matrix[:3, 3] = -matrix[:3, :3] @ origin
    return matrix


def perspective(fov_y: float, aspect: float, near: float, far: float) -> NDArray[np.float64]:
    """Standard perspective projection; fov_y is the vertical field of view."""
    if not MIN_FOV <= fov_y <= MAX_FOV:
        raise ValueError("Field of view must lie between 20 and 120 degrees.")
    if not math.isfinite(aspect) or aspect <= 0:
        raise ValueError("Aspect ratio must be finite and positive.")
    if not 0 < near < far:
        raise ValueError("Projection requires 0 < near < far.")
    f = 1.0 / math.tan(math.radians(fov_y) / 2.0)
    matrix = np.zeros((4, 4))
    matrix[0, 0] = f / aspect
    matrix[1, 1] = f
    matrix[2, 2] = (far + near) / (far - near)
    matrix[2, 3] = -2.0 * far * near / (far - near)
    matrix[3, 2] = 1.0
    return matrix


def framing_distance(subject_height: float, fov_y: float, fill: float = 0.7) -> float:
    """Distance at which a subject fills `fill` of the vertical view.

    Apparent size varies with the inverse of distance, so this is the same
    relationship the stage base-distance anchor uses, expressed through the
    field of view instead of a measured image span.
    """
    if not math.isfinite(subject_height) or subject_height <= 0:
        raise ValueError("Subject height must be finite and positive.")
    if not 0 < fill <= 1.0:
        raise ValueError("Fill fraction must lie within 0..1.")
    if not MIN_FOV <= fov_y <= MAX_FOV:
        raise ValueError("Field of view must lie between 20 and 120 degrees.")
    return subject_height / (2.0 * fill * math.tan(math.radians(fov_y) / 2.0))


class GhostCamera:
    """Noclip free-fly camera. It observes the stage and never alters it."""

    def __init__(
        self,
        *,
        position=(0.0, 1.65, 0.0),
        yaw: float = 0.0,
        pitch: float = 0.0,
        fov_y: float = 60.0,
        speed: float = 2.5,
        acceleration: float = 5.0,
        sensitivity: float = 1.0,
        near: float = 0.05,
        far: float = 60.0,
    ) -> None:
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("Camera speed must be finite and positive.")
        if not math.isfinite(acceleration) or acceleration <= 0:
            raise ValueError("Camera acceleration must be finite and positive.")
        if not math.isfinite(sensitivity) or sensitivity <= 0:
            raise ValueError("Camera sensitivity must be finite and positive.")
        if not MIN_FOV <= fov_y <= MAX_FOV:
            raise ValueError("Field of view must lie between 20 and 120 degrees.")
        if not 0 < near < far:
            raise ValueError("Camera requires 0 < near < far.")
        self.home = (
            np.asarray(position, dtype=float).reshape(3).copy(),
            wrap_yaw(yaw),
            clamp_pitch(pitch),
            float(fov_y),
        )
        self.position = np.asarray(position, dtype=float).reshape(3).copy()
        self.yaw = wrap_yaw(yaw)
        self.pitch = clamp_pitch(pitch)
        self.fov_y = float(fov_y)
        self.speed = float(speed)
        self.acceleration = float(acceleration)
        self.sensitivity = float(sensitivity)
        self.near = float(near)
        self.far = float(far)
        self.mode = FREE
        self.velocity = np.zeros(3)

    def reset(self) -> None:
        """Return to the pose the camera started from and stop moving."""
        position, yaw, pitch, fov_y = self.home
        self.position = position.copy()
        self.yaw, self.pitch, self.fov_y = yaw, pitch, fov_y
        self.velocity = np.zeros(3)
        self.mode = FREE

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown camera mode: {mode}")
        self.mode = mode
        self.velocity = np.zeros(3)

    def set_fov(self, fov_y: float) -> None:
        if not MIN_FOV <= fov_y <= MAX_FOV:
            raise ValueError("Field of view must lie between 20 and 120 degrees.")
        self.fov_y = float(fov_y)

    def look(self, yaw_counts: float, pitch_counts: float) -> None:
        """Apply relative pointer motion in device counts."""
        if not math.isfinite(yaw_counts) or not math.isfinite(pitch_counts):
            raise ValueError("Pointer motion must be finite.")
        gain = DEGREES_PER_COUNT * self.sensitivity
        self.yaw = wrap_yaw(self.yaw + yaw_counts * gain)
        self.pitch = clamp_pitch(self.pitch - pitch_counts * gain)

    def aim_at(self, target, *, distance: float | None = None) -> None:
        """Point at a world position, optionally pulling back to a distance."""
        point = np.asarray(target, dtype=float).reshape(3)
        if not np.isfinite(point).all():
            raise ValueError("Camera target must be finite.")
        if distance is not None:
            if not math.isfinite(distance) or distance <= 0:
                raise ValueError("Framing distance must be finite and positive.")
            forward, _, _ = basis(self.yaw, self.pitch)
            self.position = point - forward * distance
        offset = point - self.position
        horizontal = math.hypot(offset[0], offset[2])
        if horizontal < 1e-9 and abs(offset[1]) < 1e-9:
            return
        self.yaw = wrap_yaw(math.degrees(math.atan2(offset[0], offset[2])))
        self.pitch = clamp_pitch(math.degrees(math.atan2(offset[1], horizontal)))

    def update(self, command: CameraCommand, dt: float) -> None:
        """Integrate one frame of input. Movement is frame-rate independent."""
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("Frame time must be finite and non-negative.")
        # Look is applied before any frame-time gate. A pointer delta is already
        # a displacement, so it must not be scaled by dt and must not be lost on
        # a zero-length frame: the caller has no way to hand it back.
        if command.yaw_delta or command.pitch_delta:
            self.look(command.yaw_delta, command.pitch_delta)
        if dt == 0:
            return
        dt = min(dt, 0.25)
        if self.mode == ATTACHED:
            self.velocity = np.zeros(3)
            return
        forward, right, _ = basis(self.yaw, self.pitch)
        wish = forward * command.forward + right * command.side
        wish[1] += command.up
        speed = self.speed / 2.0 if command.slow else self.speed
        magnitude = float(np.linalg.norm(wish))
        if magnitude > 1e-9:
            wish = wish / magnitude * min(magnitude, 1.0) * speed
        else:
            wish = np.zeros(3)
        # Velocity approaches the target exponentially. Using the exact decay
        # rather than acceleration * dt matters on a long frame, where the
        # linear form overshoots and can reverse velocity outright.
        decay = math.exp(-self.acceleration * dt)
        previous = self.velocity
        self.velocity = wish + (previous - wish) * decay
        if float(np.linalg.norm(self.velocity)) < 1e-4:
            self.velocity = np.zeros(3)
        # Integrate that curve analytically instead of stepping by the end
        # velocity. A rectangle step leaves position frame-rate dependent: a
        # one-second move differs by about three percent between 15 and 120 fps.
        # The closed form is the integral of the same exponential approach.
        self.position = (
            self.position + wish * dt + (previous - wish) * (1.0 - decay) / self.acceleration
        )

    def view(self) -> NDArray[np.float64]:
        return view_matrix(self.position, self.yaw, self.pitch)

    def projection(self, aspect: float) -> NDArray[np.float64]:
        return perspective(self.fov_y, aspect, self.near, self.far)

    def view_projection(self, aspect: float) -> NDArray[np.float64]:
        return self.projection(aspect) @ self.view()

    def pose(self) -> dict[str, object]:
        """A readable pose, in the spirit of spec_pos: position plus angles."""
        return {
            "mode": self.mode,
            "position": [round(float(v), 4) for v in self.position],
            "yaw": round(self.yaw, 3),
            "pitch": round(self.pitch, 3),
            "fov": round(self.fov_y, 2),
        }

    def go_to(self, position, yaw: float, pitch: float) -> None:
        """Jump to a stored pose, as spec_goto does, staying in free mode."""
        point = np.asarray(position, dtype=float).reshape(3)
        if not np.isfinite(point).all():
            raise ValueError("Camera position must be finite.")
        self.position = point.copy()
        self.yaw = wrap_yaw(yaw)
        self.pitch = clamp_pitch(pitch)
        self.velocity = np.zeros(3)


def project_to_screen(points, camera: GhostCamera, width: int, height: int):
    """World metres to pixels, with a mask for what is actually in front.

    Returns an (N, 3) array of x pixels, y pixels and view-space depth, plus a
    boolean mask. Depth is kept so the existing depth buffer can order triangles
    without the renderer needing to know a camera was involved at all.

    Points at or behind the near plane are reported invalid rather than being
    projected. A point behind the camera still produces finite pixels after the
    perspective divide, mirrored through the origin, so drawing it would place
    geometry on screen that should not be visible.
    """
    if width < 1 or height < 1:
        raise ValueError("Projection requires a usable viewport.")
    world = np.asarray(points, dtype=float).reshape(-1, 3)
    if not np.isfinite(world).all():
        raise ValueError("World points must be finite.")
    homogeneous = np.column_stack((world, np.ones(len(world))))
    eye = homogeneous @ camera.view().T
    depth = eye[:, 2]
    valid = depth > camera.near
    clip = eye @ camera.projection(width / height).T
    w = np.where(np.abs(clip[:, 3]) < 1e-12, 1e-12, clip[:, 3])
    ndc = clip[:, :3] / w[:, None]
    screen = np.empty((len(world), 3))
    screen[:, 0] = (ndc[:, 0] * 0.5 + 0.5) * width
    screen[:, 1] = (0.5 - ndc[:, 1] * 0.5) * height
    screen[:, 2] = depth
    return screen, valid


def stand_off(camera: GhostCamera, subject_height: float = 1.8, fill: float = 0.7) -> float:
    """Distance that frames a subject of this height at the camera's field of view."""
    return framing_distance(subject_height, camera.fov_y, fill)


def dolly_zoom(distance: float, fov_y: float, new_distance: float) -> float:
    """Field of view that holds subject size constant while the camera moves.

    Apparent size varies with ``1 / (distance * tan(fov / 2))``, so keeping that
    product fixed pins the subject and changes only the background compression.
    """
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("Distance must be finite and positive.")
    if not math.isfinite(new_distance) or new_distance <= 0:
        raise ValueError("Distance must be finite and positive.")
    if not MIN_FOV <= fov_y <= MAX_FOV:
        raise ValueError("Field of view must lie between 20 and 120 degrees.")
    tangent = distance * math.tan(math.radians(fov_y) / 2.0) / new_distance
    result = 2.0 * math.degrees(math.atan(tangent))
    if not MIN_FOV <= result <= MAX_FOV:
        raise ValueError("Dolly zoom would leave the supported field-of-view range.")
    return result


def with_slow(command: CameraCommand, slow: bool) -> CameraCommand:
    return replace(command, slow=slow)
