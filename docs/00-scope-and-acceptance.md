# 00 - Scope and acceptance

## Product direction

TrickRoom will explore an original, full-body PS1-style VTuber inside an eventual interactive
room. Its performer drives movement and expressions through an ordinary camera feed. A future
Blender-authored, rigged avatar can now use the implemented Profile1 GLB import/animation
pipeline. Final character art remains separate from the technical interoperability fixtures.

The preceding KardboardCode work supplies historical lessons, not a fixed avatar, dependency
or technology mandate. This prototype has its own source, environment, documentation, tasks
and context store. The original reference image mentioned in the request was not available
as a local attachment during implementation; no likeness or asset-copying claim is made.

## First milestone

The first milestone is deliberately usable before character modeling:

- Acquire the same IP Webcam app's MJPEG feed.
- Track a single person's full visible body, including an independently tracked face.
- Draw a coherent silhouette/outline, torso, limbs, joints and connected head on a synthetic stage.
- Show eyes, mouth, smile, brows, gaze and head orientation responding to face measurements.
- Support whole-body framing while also handling feet/lower legs cropped from the image.
- Keep the display responsive while camera acquisition and inference run independently.
- Explain what's tracked, unavailable, stale or merely demonstrated.
- Provide a native control panel, easy Windows launch, documentation, journal and numbered TODOs.

The later, explicitly requested reference revision adds an authored procedural character closely
following the supplied visual direction. It replaces the bare mannequin while leaving the original
capture/tracking contract intact. Contour/skeleton overlays remain available but now default off.

## What is intentionally absent

No final-art Blender character, foot locking, physical cloth, dense
finger tracking, object interaction, arbitrary object-depth occlusion, virtual camera producer,
audio capture, identity recognition, multi-performer selection or automatic recording.

Blender GLB import, skinning, facial morphs, textures, clip previews and mapped retargeting are
implemented in workstreams13-14, with the detailed authoring handbook in15.
Workstream20 adds owned native inference, world-space rig motion, bounded limb solving,
interpolation and explicit face calibration. It is not full-body contact/physics reconstruction.
The initial body was an image-space visualization. The reference revision instead poses authored
3D clothing/head parts from image coordinates and model-relative depth, using real OpenGL depth
testing. This is not evidence of a recovered human surface or a finished skinned avatar.
The segmented silhouette is a boundary estimate, not a watertight 3D mesh.

## Acceptance boundaries

| Workstream | Engineering condition | Separate live condition |
|---|---|---|
| Camera | Fragmented MJPEG/auth/replay, latest-frame behavior and cleanup are exercised | Actual phone transport and orientation |
| Tracking | Real pose/face models return normalized results on suitable public input | Real movement, glasses, distance and lighting |
| Body coverage | Low confidence/out-of-bounds joints are excluded; partial status is explicit | Visually correct body alignment in actual framing |
| Expressions | Independent controls reach the head; real face inference produces them | Comfortable/accurate blinks, smiles and speech |
| Output | Avatar renderer accepts no input image; avatar/clean frames stay synthetic | User appearance and motion acceptance |
| Latency | Bounded local throughput/observation-age measurements | Physical camera-to-display measurement |

Model confidence is not ground truth. A high-confidence in-frame landmark can still be wrong
or inferred through an occlusion. Observations and raw diagnostics never add missing limbs.
An explicit GLB presentation option can retain labelled held/rest poses; these are not detections.
The application cannot guarantee that the ML model never hallucinates a confident joint.

`TODO\07_LIVE_CAMERA_QUALIFICATION.todo` owns live evidence. It may remain blocked while the
engineering implementation is complete. This is not a hidden failure or a reason to invent results.
