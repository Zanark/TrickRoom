# Original Blender conformance characters

These simple technical rigs validate the runtime; they are **not the final avatar artwork**.

- `TrickRoom-Conformance.blend/.glb/.trickroom.json`: 23 named bones, weighted mesh,
  embedded checker texture, twelve facial keys, wave/facial clips and default morph gaze.
- `TrickRoom-EyeBones.blend/.glb/.trickroom.json`: equivalent technical geometry with actual
  eye-bone weights and the alternate bone-gaze profile.
- `conformance-build.json`: exact Blender version, generator hash and output hashes.

Create a separate copy for experiments. Do not overwrite accepted art with these fixtures.
Rebuild through `tools\blender\create_conformance_rig.py` only when deliberately updating
the interoperability baseline. The detailed authoring contract is in the handbook under `docs`.
