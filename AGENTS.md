# TrickRoom contributor guide

Read README.md, TODO\00_INDEX.todo, JOURNAL.md and the relevant numbered docs before editing.
For local cross-session continuity, hydrate this base's .agent-context if present.

This is an independent full-body VTubing experiment, not the KardboardCode avatar.
The first milestone is real camera-to-body/face tracking and synthetic visualization.
Blender GLB import/retargeting is implemented under the Profile1 contract. Final avatar artwork,
richer tracking/physics and interactive room objects remain separate work.
- Maintain docs\book\AUTHORING.md and rebuild the50-100page handbook when the export contract changes.

- Never pass camera pixels to the avatar renderer or clean output. Raw input is allowed only in
  its explicitly enabled private debug window, default off. No automatic recording.
- Camera-auth defaults must stay in ignored Windows-user-encrypted local storage, never source/docs/memory.
- Treat off-frame/low-confidence joints as unavailable in observations and diagnostics.
  Only explicit relaxed GLB presentation may display labelled held/rest poses; stale input clears.
- Keep the native tracking SDK in the owned child process. Static face-connectivity data lets
  Studio render debug views without loading MediaPipe. Personal face calibration stays in memory.
- Studio renderer mutations and OpenGL operations belong to GraphicsWorker. Queue them; keep Tk
  access on the UI thread. Reject obsolete draw epochs and clear stale displays even during slow draws.
- Keep demo, fixture, live-camera evidence and subjective acceptance distinct.
- Preserve anatomical left/right. Mirror presentation, not model input.
- The projected room and shoe shadows are presentation, not physical floor/contact measurements.
- Do not log source URLs, credentials, raw media, landmarks or biometric data to disk by default.
- Local inference is not a network-silence guarantee: prebuilt MediaPipe has usage telemetry.
  Do not equate suppressing SDK log messages with disabling uploads; see workstream18.
- Use the isolated Python 3.12 environment; never modify a sibling project's environment or store.
- Keep numbered TODO IDs stable. Update task evidence, JOURNAL.md and affected docs together.
- Run focused tests and Ruff for code changes. Record actual limitations, not assumed success.
- CLI reference-video export is explicit and frame-by-frame. Keep offline source clocks distinct
  from live timestamps, preserve inputs/existing outputs, and never label availability as perfect rigging.
