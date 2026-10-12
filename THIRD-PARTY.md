# Third-party components and test inputs

TrickRoom uses installed dependencies; their licenses/notices remain applicable. It does not
claim ownership of their models. The one small vendored-data exception is the static facial
connectivity described below; it avoids importing native tracking libraries in the studio.

- MediaPipe: local pose/face inference. Official model downloads are explicit, versioned and
  SHA256-verified by `src\trickroom\models.py`. Review upstream distribution/model terms before
  bundling weights in any future release.
- OpenCV Contrib and NumPy: image ingestion, geometry and rendering.
- ModernGL and glcontext: local OpenGL3.3 depth-tested synthetic graphics; no graphics service.
- Pillow and Python/Tkinter: synthetic image presentation and native controls.
- Pytest and Ruff: development validation.

`src\trickroom\face_topology.json` contains deduplicated face-connection indices derived from
MediaPipe's Apache-2.0-licensed `tasks/python/vision/face_landmarker.py`. Source version/hash
are embedded in the JSON, and the upstream license is retained in `face_topology.LICENSE`.
`tools\update_face_topology.py` regenerates this data by parsing the installed source without
importing or executing the SDK. This is topology data, not a tracking model or private landmarks.

The application does not capture audio. MediaPipe's dependency environment may contain audio
packages such as sounddevice; their installation is not microphone use.

The optional public-fixture check uses an official MediaPipe pose asset and the Pixabay fitness
photo linked by the official Pose tutorial. Their source URLs and SHA256s are recorded in
`tools\verify_tracking.py`; raw fixtures are local-only and not shipped as project art.
Documentation images/GIF are newly generated synthetic visuals, not those photographs.

The reference character revision is guided by the two owner-supplied sheets listed in
`docs\10-reference-avatar.md`. Private copies/hashes are retained locally; the sheets themselves
are not bundled, republished or used as pasted runtime textures. Rights beyond owner supply
were not independently established. No publication was requested.

The repository did not originally specify a project license. This prototype does not invent
one or publish a release; licensing/release packaging is a later explicit decision.
