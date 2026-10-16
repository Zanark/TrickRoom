# Ghost camera: viewing the stage from anywhere

Status: usable. Section **08 / GHOST CAMERA** in the Studio control panel flies the view with
WASD and the mouse, and `tools\check_ghost_camera.py` renders stills from any angle offline. It
applies to imported GLB models only. Read
[what is not implemented yet](#what-is-not-implemented-yet) before relying on anything here.

The capture camera decides what the performer is doing. The ghost camera decides where that
performance is watched from. Keeping those two jobs apart is the whole feature.

## Why this needs a new camera at all

TrickRoom's renderer has never had a camera. The vertex shader in `src\trickroom\raster.py`
receives vertices that are already in pixel coordinates and maps them straight to clip space:

```glsl
uniform vec2 size;
gl_Position = vec4(position.x / size.x * 2.0 - 1.0, ...)
```

There is no view matrix and no projection matrix. Placement is a uniform scale plus a
translation (`src\trickroom\assets\presentation.py`), and `z` exists only so the depth buffer can
order triangles. The perspective lab is a background image cached per window size, not geometry.

So the stage is 2.5D: real depth testing, no viewpoint. A movable camera is not a control bolted
onto an existing 3D view. It requires introducing the 3D view.

## The principle borrowed from replay systems

Every mature replay system separates recorded world state from the view over it. Quake's demo
writer makes the split literal: each frame is a length, three view angles, and then the network
message, with the camera angles written *beside* the state rather than inside it
(`WinQuake/cl_demo.c`). Demo playback then swaps a file in for the network socket and leaves the
client above it unchanged.

TrickRoom inherits the same invariant:

> The ghost camera is a view over observations. It never becomes part of them.

Concretely, in `src\trickroom\ghostcam.py` the camera holds a position, an orientation, a field of
view and a velocity. It holds no landmarks, no asset and no runtime handle. A test asserts that
directly. Moving the camera cannot change what the tracker reported, cannot change the recorded
timestamps, and cannot change availability or diagnostics.

## Coordinate convention

Metres, `+X` right, `+Y` up, `+Z` away from the viewer, floor at `y = 0`. This matches
`trickroom.room`, which already projects with `x / z` for positive depth and places the eye at
1.65 m.

This is deliberately **not** the OpenGL default of looking down `-Z`. The room came first and one
convention is better than two. The projection matrix in `ghostcam.py` is written for this
handedness. Do not paste a `gluPerspective` matrix over it without re-deriving the signs.

## Camera modes

Modes are identified by name, never by number. Valve's own spectator enum moved `ROAMING` from 6
to 7 when a mode was inserted mid-list, which silently broke every comparison written against the
integer. Names cost nothing and do not drift.

| Mode | Meaning |
| --- | --- |
| `free` | Noclip fly. Six degrees of freedom, attached to nothing. The default. |
| `orbit` | Rotate about a pivot at a fixed radius. For inspecting the character. |
| `attached` | Pose driven by the subject. Look controls still work; flying does not. |

`free` is the mode that answers the original request: move anywhere, frame any shot.

## Ghost movement

"Ghost" means noclip, and noclip is defined by what it omits. Quake's implementation is four
lines whose header comment reads "A moving object that doesn't obey physics": no gravity
accumulation, no collision trace, no ground friction. Position is pure Euler integration,
`position += velocity * dt`.

TrickRoom does the same. There is no floor collision for the camera and no gravity. A camera has
no body, and a camera trapped by the room's geometry would be useless for framing shots.

Three details decide whether a free camera feels controllable:

**Forward follows the look vector; up does not.** Flying forward while pitched down descends,
which is what makes a free camera feel like flying. Vertical input stays world-up regardless of
where the camera is pointing, which is what stops it feeling like a rollercoaster. Source composes
its spectator velocity the same way.

**The desired velocity is clamped before acceleration, not after.** Clamping the result distorts
diagonals, because the diagonal is long before it is scaled. Clamping the wish vector preserves
direction and only limits magnitude.

**The slow modifier halves speed.** It is a precision aid for framing, not a sprint. Source's
`IN_SPEED` does exactly this, and it is worth stating because the opposite is widely assumed.

## Camera mathematics

Orientation is yaw and pitch in degrees, with roll held at zero while flying. Uncommanded roll
destroys the horizon that a pilot navigates by; roll belongs to deliberate cinematic work.

The basis is derived directly from the angles:

```
forward = (sin yaw * cos pitch,  sin pitch,  cos yaw * cos pitch)
right   = (cos yaw,              0,         -sin yaw)
up      = forward x right
```

**Pitch is clamped to +/-89 degrees.** Two different failures meet at the pole and are often
conflated. The horizontal component of `forward` is `cos(pitch)`, which reaches zero at 90
degrees, so yaw can no longer be recovered from the look direction and the view snaps under float
noise. Separately, the Euler decomposition itself loses a degree of freedom there, which is gimbal
lock proper. Clamping short of the pole avoids both. 89 degrees is used rather than the tighter
limits engines apply to players, because a camera must be able to look very nearly straight down.

Yaw wraps into `-180..180` so that any future interpolation takes the shortest arc. Blending
`359` to `1` the long way round is the classic replay-camera artefact.

The view matrix is the inverse of the camera's world transform. Because the basis is orthonormal
its inverse is its transpose, so the rows are the basis vectors and the translation column is the
negated dot products, not a naively transformed position.

Apparent size follows

```
fraction of view height = subject height / (2 * distance * tan(fov / 2))
```

which gives two useful tools for free. `framing_distance()` inverts it to answer "how far back do
I stand to fill 70 percent of frame with a 1.8 m character". `dolly_zoom()` holds
`distance * tan(fov / 2)` constant so the subject stays exactly the same size while the background
compression changes.

This is also the same inverse-distance relationship the stage base-distance anchor uses
(`src\trickroom\placement.py`, workstream 28). One is expressed through a measured image span and
the other through a field of view, but they describe the same geometry.

## Frame rate and feel

**Movement scales with frame time. Mouse look does not.** This is the most common free-camera bug
and the two halves pull in opposite directions. Velocity is a rate, so it must be multiplied by
`dt`. A mouse delta is already a displacement; multiplying it by `dt` makes sensitivity change
with frame rate. Source computes rotation as `counts * m_yaw * sensitivity` with no frame-time
term at all, and TrickRoom follows it.

Velocity approaches the desired velocity exponentially:

```
blend = 1 - exp(-acceleration * dt)
```

The familiar `acceleration * dt` is the linear approximation of this. It is accurate at a steady
frame rate and wrong on a long frame, where it overshoots and can reverse velocity outright.
Using the exact form costs one `exp` call. Frame time is additionally clamped so a stalled frame
cannot teleport the camera.

Default sensitivity follows Source's `m_yaw * sensitivity`, which is `0.022 * 3`, giving
0.066 degrees per pointer count.

## Honest limits

**The camera cannot improve the pose estimate.** It changes only the viewpoint.

Pose comes from one camera. MediaPipe world landmarks are a monocular depth estimate, not a
measurement. Looking from the front hides depth error because it projects away. Rotating 90
degrees to the side turns that same error into the silhouette, which is the worst case. Expect
side and rear views to look materially worse than the front, and expect that to be a property of
single-camera capture rather than a bug in this feature.

The imported GLB path will hold up better than the built-in character. An imported rig has an
authored skeleton with fixed bone lengths constraining the solve, while the built-in character is
assembled from image-space landmarks and has no real depth to show. `docs\14-vseeface-research.md`
reaches the same conclusion about where apparent full-body quality actually comes from.

So "any angle" realistically means a useful arc around the front, widening as rig constraints
improve. It should be described that way rather than promised as free orbit.

The room is still a presentation surface. Flying the camera through it does not make it a measured
physical space, and foot shadows remain decorative rather than contact evidence.

## How the viewpoint reaches the screen without touching the shaders

The renderer still has no view or projection stage, and it did not need one. The shader consumes
pixel coordinates, so the camera transform happens before the data reaches it:
`ghostcam.project_to_screen()` takes world metres through the view and projection matrices, does
the perspective divide, and returns pixel coordinates plus **view-space depth**. That depth goes
into the existing depth buffer, so triangles still sort correctly and the rasteriser never learns
a camera was involved.

`assets\presentation.camera_batches()` uses this for the imported rig, which already carries real
geometry in metres. `room.camera_room()` reuses the existing room surface definitions, which were
already expressed in world coordinates, and simply projects them through the camera instead of the
fixed stage projection.

Triangles and room tiles with any vertex at or behind the near plane are **dropped, not clipped**.
Proper clipping would split them against the plane. The visible consequence is that geometry very
close to the camera thins out rather than tearing.

## What is not implemented yet

Implemented and covered by tests:

- Camera state, named modes, noclip movement, mouse look, framing helpers, stored-shot pose.
- View and projection matrices, and world-to-pixel projection with a behind-camera mask.
- The camera-driven room, including looking away from the room entirely without raising.
- Imported-rig rendering from an arbitrary viewpoint.
- Frame-rate independence, speed clamping, pitch clamping and input validation.

Verified end to end by `tools\check_ghost_camera.py`, which renders one identical pose from six
positions and checks every shot is distinct and contains the subject.

While the pointer is captured it is warped back to the middle of the stage after every motion
event, and the returning event is ignored. Without that the cursor reaches the edge of the stage,
motion events stop and the camera stops turning part way round. With it, yaw is genuinely
unlimited: a check pushes 9600 pixels of pointer travel across a 1017 pixel stage and accumulates
633.6 degrees, which is more than a full circle and exactly the travel multiplied by the 0.066
degrees-per-count sensitivity.

Pointer events are bound to the stage **label**, not the frame around it. The label fills the
frame, so a binding on the frame alone never fires. That was a real defect: the focused tests
injected look deltas directly and could not see it, which is why
`tools\check_ghost_input.py` drives genuine Tk click and motion events instead.

Studio section 08 provides the enable toggle, click-to-capture pointer look, WASD and
`Q`/`E`/`Space`/`Ctrl` movement, `Shift` precision, field-of-view and speed sliders, a reset and a
live pose readout. `Esc` releases the pointer before it disconnects, so flying never costs you the
source. Input is collected in Studio and handed to the camera as an abstract command, which is why
a focused text field simply stops producing movement instead of fighting the camera.

Not implemented:

- The built-in procedural character has no camera path. It is posed from image-space landmarks and
  has no real depth to view, so only imported GLBs can be viewed from another angle. With the
  built-in character the stage renders normally and the camera controls do nothing.
- Orbit and attached modes are defined and validated but have no subject wired to them.
- Near-plane clipping drops triangles instead of splitting them.
- No cinematic paths, no stored shot list, no export from a chosen angle.
- The stage still places the character by apparent size rather than in world space, so the camera
  path uses an explicit origin. Workstream 28 is what removes that.

See `TODO\29_GHOST_CAMERA.todo` for the sequence.

## Sources

The design above is taken from primary engine source rather than convention or recollection.
Each claim in this document traces to one of these.

- Quake, GPL release, WinQuake tree: <https://github.com/id-Software/Quake>
  - `cl_demo.c` - demo frames store view angles beside the network message; playback
    double-buffers consecutive angle samples.
  - `cl_main.c` - recorded angles are interpolated with explicit +/-180 degree wrapping, and the
    blend fraction is clamped so playback interpolates rather than extrapolates.
  - `sv_phys.c` - noclip integration is position and angle Euler steps with no gravity,
    collision or friction.
  - `sv_user.c` - vertical input is only honoured when the mover is not walking; noclip assigns
    velocity directly with no acceleration ramp.
  - `cl_input.c` - pitch and roll clamps. These are gameplay limits, not the camera limits used
    here.
- Source SDK 2013: <https://github.com/ValveSoftware/source-sdk-2013>
  - `src/game/shared/shareddefs.h` - the spectator mode enum, including the inserted mode that
    shifted `ROAMING` from 6 to 7. This is why modes here are named, not numbered.
  - `src/game/client/hltvcamera.cpp` - roaming movement is annotated as a copy of the noclip
    mover; forward and right come from the view angles while vertical is world-space; the desired
    velocity is clamped before acceleration; the speed modifier halves the factor; input is
    consumed from a buffered command rather than read from a device.
  - `src/game/shared/movevars_shared.cpp` - spectator and noclip speed, acceleration and friction
    defaults.
  - `src/game/client/in_mouse.cpp` - `m_yaw` 0.022 and `sensitivity` 3, giving 0.066 degrees per
    count, computed with no frame-time term.
- Valve Developer Community, CS:GO spectator tools:
  <https://developer.valvesoftware.com/wiki/CS:GO_Spectator_Tools> - `spec_mode`, `spec_pos` and
  `spec_goto`, and the detail that a preset camera is implemented as free roam seeded with a pose
  rather than a locked mode. Community-maintained documentation.
- OpenGL reference for `gluLookAt` and `gluPerspective`:
  <https://registry.khronos.org/OpenGL-Refpages/gl2.1/xhtml/gluLookAt.xml> and
  <https://registry.khronos.org/OpenGL-Refpages/gl2.1/xhtml/gluPerspective.xml> - the standard
  view and projection constructions this module re-derives for its own handedness.
