# 09 - References and provenance

Public API references checked during implementation on 2026-10-11:

- [MediaPipe Pose Landmarker Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python)
  - Running modes, timestamps, pose/world coordinates, presence/visibility and segmentation.
- [MediaPipe Face Landmarker Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python)
  - Face mesh, blendshapes, transformation matrices and anatomical left/right mirroring behavior.
- [Official Pose Python tutorial](https://github.com/google-ai-edge/mediapipe-samples/blob/main/examples/pose_landmarker/python/%5BMediaPipe_Python_Tasks%5D_Pose_Landmarker.ipynb)
  - Identifies the publicly accessible Pixabay fitness photograph used by the positive fixture.
- [Official MediaPipe pose asset](https://storage.googleapis.com/mediapipe-assets/pose.jpg)
  - Separate side-profile body fixture.
- [Pixabay source page for the tutorial fixture](https://pixabay.com/photos/girl-woman-fitness-beautiful-smile-4051811/)
  - Public test input, not a bundled avatar or original TrickRoom photograph.

The fixture and model SHA256s live with the tools that consume them. Input photographs are not
committed, shown in the documentation gallery, or used as texture assets.

## Historical references

The initial read-only orientation covered the KardboardCode-VTuber implementation, engineering
documents and 205-page book, both its repository and older OBS/PNGTuber context stores, relevant
zmem chronology, and the Almost Us Blender workflow. These established:

- latest-frame and clear timing semantics;
- image-free/privacy-conscious presentation boundaries;
- the difference between tracking availability and geometrically correct results;
- failures of inferred-depth/marker heuristics in a different project;
- numbered documentation/TODO and provenance practices.

They do not establish live success for TrickRoom or require carrying over the same renderer,
avatar, visual design or tracking choices. Private source locations and detailed session
provenance stay in the local context store rather than being copied into public-facing docs.
