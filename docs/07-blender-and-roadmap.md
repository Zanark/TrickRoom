# 07 - Future Blender avatar and roadmap

## Current status

The GLB import/animation pipeline is now implemented in workstreams13-14, with the authoring
handbook in15. See [Blender model support](12-blender-models.md). The final reference-art character
has not been converted into an accepted Blender rig; that artistic task remains separate.
The first [core motion upgrade](15-core-motion-upgrade.md) now provides world-space rig posing,
bounded limb constraints, interpolation and optional labelled loss transitions.

## Preserved artistic direction

The owner wants a PS1-style full-body avatar in Blender, including a rig, animated from Python
using body movement and facial expressions. The implemented export contract is now Profile1
self-contained GLB2 with supported skins, morphs, textures and clips. Future expansions should
remain explicit rather than implying every Blender feature already works.

M1 answers: can we obtain usable body/face observations and see them clearly?
M2 will answer: how should those observations drive an original character?
M3 may add the room and interactable objects recorded in the repository's original README.

## Candidate seams already present

`Observation` separates camera/tracker specifics from presentation. Image-space joints,
world-space estimates, face orientation and named expression controls have distinct fields.
The imported-model retargeter now consumes this contract without importing camera/credential logic.

That does not make normalized coordinates bone rotations. The implemented retargeter supplies
rest-direction rotation, hierarchical skinning and overall scale calibration. Richer retargeting
still requires
rest-pose calibration, coordinate conversion, scale policy, bone hierarchy, joint constraints,
root motion and confidence-aware behavior. Foot/hand contacts and crossed limbs need dedicated
evaluation. A single camera cannot directly observe hidden limbs or accurate arbitrary object depth.

The current depth-tested procedural renderer remains available alongside the implemented
rigged-model path. Nothing here requires ModernGL to be the final rendering backend or
MediaPipe to be the only tracking option. Evaluate alternatives with reproducible comparisons.

## Model and rig decisions to make later

- Original visual identity, proportions and silhouette; do not reuse the cardboard-head design.
- Polygon budget, flat/smooth normals, texture size, palette and UV/atlas conventions.
- Humanoid bone names/hierarchy, units, axes and reference/rest pose.
- Whether facial expression uses shape keys, bones, texture swaps or a combination.
- Export contract such as glTF/GLB or another evaluated runtime format.
- Calibration, missing-joint behavior, IK/constraints and contact/occlusion policy.
- Renderer/runtime choices, measured cost and optional virtual-camera transport.

These are intentionally open rather than questions blocking the current prototype.

## Blender production lessons retained

The Almost Us workflow showed useful general practices:

- Start reproducible generation from a known empty Blender state.
- Separate geometry/material authoring, render execution and post-processing.
- Save editable `.blend` sources, generator parameters, seeds and exact source snapshots.
- Use bounded serialized GPU jobs and inspect low-cost previews before promotion.
- Check script exit codes; Blender's `--python-exit-code 1` exposes Python failures.
- Treat metadata plus old pixels as potentially inconsistent after interrupted renders.
- Keep failed candidates and source hashes so a correction remains explainable.
- Validate geometry/exports and inspect them visually; technical checks do not supply art approval.

None of the album's no-human-scene rule, lighting style, 3000px covers or scene content is a
requirement for TrickRoom. Only the reusable engineering lessons are relevant.
