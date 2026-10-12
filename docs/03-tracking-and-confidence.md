# 03 - Tracking, confidence and coordinates

## Pose and silhouette

MediaPipe Pose Landmarker Lite returns 33 normalized image-space landmarks, corresponding
world-space estimates and a person segmentation mask. The longest pose-inference input side is
768 pixels by default; choose 512, 640, 768, 960 or 1280 with `--tracking-size`.
Resize preserves aspect ratio and never upscales the source in the application.

The normalizer retains image and world points in immutable contracts. World coordinates are
model estimates around the hips, not measurements from a depth sensor or proven room-space
calibration. The built-in renderer uses image coordinates and approximate pose depth to orient
its procedural parts. Enhanced imported rigs use eligible world directions for articulation,
with independently filtered world coordinates; image coordinates still control framing and
availability. Legacy image-space rigging remains available for comparison.

The silhouette:

1. Accepts the model's HxW or HxWx1 mask.
2. Thresholds person probability at 0.55.
3. Applies a 3x3 morphological close.
4. Finds external contours, retaining at most three significant components.
5. Approximates polygons with an epsilon of `max(1.2, perimeter * 0.002)`.
6. Returns normalized polygon points, discarding mask/image colors.

This produces a low-poly outline that can retain clothing silhouette. It is not dense body
reconstruction, guaranteed clothing separation, object-depth estimation or hand segmentation.

## Joint availability

`Point.usable()` requires finite coordinates, x/y inside [0,1], visibility at least 0.5 and
presence at least 0.5. A line segment is drawn only when both endpoints pass.
An invisible joint is not clamped to an image edge or supplied by a guessed limb length.

**FULL BODY** means the shoulders, elbows, wrists, hips, knees, ankles and foot indices pass
these checks. Otherwise a detected body is **PARTIAL BODY**. The displayed count is out of all
33 pose landmarks, including head/hand/foot anchors, not 33 separate skeletal bones.

These gates check the model's estimates, not independent ground truth. The model itself can
place an occluded landmark confidently inside the image. Actual framing and motion review are
still necessary. Dense finger articulation and contact reasoning are deferred.

## Face acquisition in full-body framing

A full-body person may occupy most of an image while the face occupies very few pixels. Running
a face detector only on a downsized entire frame can make that harder.

The prototype uses the same frame's pose head points (nose, eyes, ears and mouth anchors) and
shoulder span to propose a square head crop. It reads that crop from the **original-resolution
decoded image**, then limits it to 512 pixels for face inference. If no reliable crop is
available, it uses the full frame bounded to 960 pixels. After every eight crop misses it tries
full-frame reacquisition once.

Crop results are mapped back into original normalized image coordinates. A full-frame fallback
face must still lie inside the current expected head region when pose supplies one. This reduces
obvious body/face mismatches; it is not a multi-person identity-association system.

The crop cannot recover motion blur, hidden eyes or missing source detail. A tested side-profile
fixture did not acquire a face even with six crop sizes; the correct behavior was pose-only head
display, not an invented successful expression track.

## Face controls

The 478-point face result, 52 blendshape outputs and facial transformation matrix supply:

| Display control | Source |
|---|---|
| Independent eye closure | `eyeBlinkLeft`, `eyeBlinkRight` |
| Jaw/mouth opening | `jawOpen` |
| Smile | Average of `mouthSmileLeft` and `mouthSmileRight` |
| Each eyebrow | Inner/outer brow raise minus corresponding brow-down |
| Approximate gaze | Paired eye look-in/out/up/down scores |
| Head pitch/yaw/roll | Rotation decomposition of the facial transformation matrix |

Facial-oval points establish head bounds; moving irises do not resize the head.
Missing landmarks, blendshapes, non-finite values or invalid matrices are errors rather than
silent neutral-face substitutions.

The renderer's mouth amplitude is amplified and eye closure is thresholded for readability.
Those mappings are prototype art controls, not anatomical measurements or emotion classification.
Smile does not mean the program inferred a mood.

## Left, right and mirroring

The model always sees unmirrored rotated camera pixels. Subject-anatomical left/right is retained
in contracts; the final synthetic image alone is mirrored when selected. For a front-facing
unmirrored face, anatomical left is screen-right. Mint marks left, lilac marks right.

The magnified head detail uses the same mirroring as the stage; text is drawn afterward so it
never reverses. Do not add a second eye swap in tracking to compensate for a display mirror.
If a phone app itself emits an already mirrored stream, disable that app setting for this contract.

## Motion filtering

One Euro filters smooth available joint coordinates and head position, size and angles.
Low-pass strength increases during slow motion and relaxes as velocity increases:

```text
derivative = (raw - previous_raw) / dt
cutoff = minimum_cutoff + beta * abs(filtered_derivative)
alpha = 1 / (1 + 1 / (2*pi*cutoff*dt))
filtered = previous_filtered + alpha * (raw - previous_filtered)
```

Filters reset after gaps over 500 ms, time reversal or loss of that joint. Head angles are
unwrapped before filtering to avoid sweeping through zero when crossing +/-180 degrees.
Confidence is not filtered upward. Expressions bypass this motion filter so short blinks are
not erased; MediaPipe may still apply its own tracking/smoothing internally.

The optional **Face response** layer separately calibrates/remaps a presentation copy and leaves
detector coefficients untouched. Its direct blink path preserves brief winks. Enhanced GLB rigs
also interpolate display poses and optionally blend lost regions toward rest; neither process
adds detections or changes the raw skeleton. See [core motion](15-core-motion-upgrade.md).
