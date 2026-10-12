# 04 - Synthetic reference-avatar rendering

## Character, not diagnostic anatomy

The active avatar follows the two supplied sheets described in
[the reference contract](10-reference-avatar.md): jagged dark hair, warm angular face, beige
headphones, charcoal hoodie, olive cargo trousers and cream/taupe sneakers.
The original mint/lilac mannequin is preserved in the local revision archive, not drawn as the
default costume. Camera contour and skeletal links are now opt-in diagnostics.

The current character is an assembly of authored 3D parts. It is not recovered from the reference
pixels, imported from Blender, skinned to a finished rig, or inferred as a human surface.

## Geometry and material detail

`avatar.py` supplies cached templates for:

- a bevelled head, stepped jaw shading and minimal dark eyes/mouth;
- layered hair volume, fringe, crown spikes and rear hair coverage;
- polygonal headphone cups, dark cushions, bevelled rims and a curved headband;
- hoodie body, front collar folds, back hood, drawstrings, kangaroo pocket and ribbed hem;
- roomy upper/lower sleeves and cuffs;
- broad trouser segments, outer thigh pockets/flaps, lower-leg flare and cuffs;
- block hands and shoes with substantial soles, toe ramps, panels and laces.

Material tiles are deterministic per-part color variations, generated once in object space.
They move with clothing instead of swimming over screen pixels or changing randomly every frame.
These coplanar color tiles contribute to the measured triangle count. The illustrative counts
printed on the supplied sheets are not treated as measurements of this implementation.

The head is intentionally larger than a tight human-face overlay to follow the reference
proportions. Position remains camera-driven with a documented proportional placement offset.
Pose-only fallback uses comparable character scale rather than shrinking back to the old mannequin.

## Posing

Body image coordinates establish screen location. Model-relative pose depth helps orient each
part's local frame and supplies inter-part depth. Shoulder/hip geometry establishes the torso
frame; sleeves and trousers align between valid endpoints. A segment is omitted when its required
endpoint is unavailable. Foot geometry requires an eligible ankle and foot index.

The simple block hands represent wrist/pose-hand anchors; they are not independently tracked
finger joints. Approximate limb ordering and depth do not establish correct real-world contact
or self-occlusion. Fixed-proportion skeletal retargeting and IK remain future work.

Face pitch/yaw/roll rotates the complete head/hair/headphone assembly. Independent closure,
jaw, smile, brows and gaze alter small facial geometry. No white cartoon sclera is introduced
because the references use narrow dark eyes. A lost face stops facial animation and labels
the pose-derived head as unavailable expression data.

## True per-pixel depth

Mean-depth painter sorting was tried and rejected: sloping triangles and closely spaced pocket/
hair surfaces overwrote each other incorrectly at three-quarter angles.

`raster.py` instead renders the synthetic triangle batch into a transparent OpenGL3.3 framebuffer
with a real depth attachment. Vertices arrive in the prototype's camera-aligned coordinate space.
The vertex shader maps x/y to the framebuffer and positive-toward-viewer z into depth. The fragment
shader outputs a flat face color, and depth testing resolves intersecting surfaces per pixel.

The context is thread-local; normal rendering stays on the UI thread. Up to four framebuffer
sizes are cached for the main stage, head inset and resizing, with older resources released.
Camera capture and MediaPipe inference remain independent workers and never enter this renderer.

The OpenGL result's alpha controls composition onto the projected synthetic lab or plain background.
The room's floor, walls, ceiling and calibration markings share one pinhole camera; details and
the distinction between decorative shadows and physical contact are in
[the room chapter](11-perspective-lab.md). No input camera
pixels or reference-sheet images enter the renderer. A missing OpenGL3.3 context is an explicit
startup failure, not a silent return to incorrect painter rendering.

## Presentation and loss

The viewport preserves camera aspect ratio. The scene generally renders near 640 pixels wide
and uses nearest-neighbor enlargement for the retro look. There is no automatic camera crop or
hidden body recentering.

The room toggle changes only the backdrop and visual shoe shadows. It does not change the avatar's
shape, inferred pose or screen position. Unavailable feet do not acquire synthetic leg/shoe geometry
just because a floor is visible.

Presentation-only mirroring occurs after rendering. The head-detail inset uses the same mirroring;
HUD text is drawn afterward and never reverses. On stale observations, live character geometry
clears after600ms. Fresh no-person input produces a waiting stage. Demo output remains labelled
even in the clean window.

## Review tools

```powershell
.\.venv\Scripts\python.exe tools\render_avatar_gallery.py
.\.venv\Scripts\python.exe tools\render_gallery.py
```

The first tool emits six authored body/head angles, six facial states, geometry counts, graphics
identity and timing/hash metadata. Back/side views are synthetic art-review poses, not a claim
of live rear-face detection. The second emits movement, crop, face-loss and stale-state visuals.

Unit coverage includes anatomy/mirroring, expression channels, availability gates, geometry
budget/cache immutability, true crossing-triangle depth, bounded target caching, explicit graphics
failure and shutdown. Visual inspection is still necessary and does not supply owner approval.
