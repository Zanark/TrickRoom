# TrickRoom memory

> Identity: the full-body VTubing engineering and creative-prototyping partner.
> Carry forward only verified decisions; distinguish history, current code and future ideas.

## People

No personal information is stored. Creative acceptance remains the project owner's decision.

## Conventions

- Independent project: full-body PS1-style VTubing, not continued cardboard-head work.
- Initial milestone: real-time body outline, skeleton, attached expressive head, no final model.
- Main avatar and clean output are synthetic. Explicitly enabled private raw-input debug is
  the only UI exception; it starts off, stays separate, and never enters output/export buffers.
- Out-of-frame/low-confidence joints remain unavailable in observations/raw diagnostics.
  Only explicit relaxed GLB presentation may show labelled held/rest poses; source staleness clears.
  ML confidence itself can still be wrong; never call it visibility ground truth.
- Prototype tech choices are revisable. Profile1 Blender support is implemented; the final
  reference-art character remains separate authoring work.
- The next reference-driven test avatar should follow near-final art direction, not a throwaway
  placeholder look. Visual target and rig/retargeting implementation maturity are separate.
- Reference character: dark jagged hair, beige over-ear headphones, warm angular face, charcoal
  hoodie, olive cargo trousers and cream/taupe sneakers. See docs\10-reference-avatar.md.
- Reference renderer uses true per-pixel depth, not mean-depth painter sorting. OpenGL3.3 support
  is explicit; graphics failure must not silently substitute incorrect rendering.
- Current character is landmark-posed procedural parts with stable color tiles, not a Blender rig.
  Contour/skeleton are optional diagnostics and start off for the reference appearance.
- The lab is five pinhole-projected synthetic surfaces. StageOptions.grid toggles the whole room;
  eligible-shoe shadows are decorative, not physical floor/contact/collision evidence.
- VSeeFace research lives in docs\14-vseeface-research.md. Distinguish measured tracking from
  calibrated/interpolated/IK/secondary animation; public reference code is not the full closed app.
- Current room art direction is near-black green panels with thin vivid green grids/borders,
  without calibration crosses. The earlier slate/cross-marker theme is historical.
- Blender interoperability uses Profile1 self-contained GLB2 with canonical or mapped humanoid
  bones/shape names. .blend is the authoring source, not a runtime file.
- Imported characters preserve bone lengths, apply morphs before LBS skinning, and retain the
  previous avatar on rejected import. Bind/clip preview is distinct from live retargeting.
- Enhanced GLB posing uses eligible filtered world directions; image landmarks still govern
  eligibility/placement. World coordinates must not use Point.usable's image-only0..1 bounds.
- Imported display scale uses image/posed-rig projected2D span ratios and per-observation
  log-scale filtering. Do not count inferred depth as screen size or latch an initial partial pose.
- Render-time rig interpolation uses arrival-adjusted timestamps and a monotonic bounded playhead.
  Held/rest/reacquiring poses do not alter observations or count as additional detections.
- Native capture/model inference is an owned spawned process with Windows kill-on-close job,
  bounded request/response IPC and explicit crash/timeout state. Keep the main-module spawn guard.
- Face debug uses licensed static topology so Studio does not import MediaPipe. Regenerate it
  with tools\update_face_topology.py and retain its upstream license when the SDK topology changes.
- Facial response is session-local and explicit. Preserve independent quick blinks, raw detector
  coefficients and no calibration-file writes; source switches/reset discard personal calibration.
- Contract changes require updating docs\book\AUTHORING.md and rebuilding the50-100page
  authoring handbook with source-citation, page/bounds and HTML checks.
- TODO\00_INDEX.todo indexes stable NN_UPPER_SNAKE_CASE.todo workstreams with status,
  dependencies, tasks, acceptance, completion evidence and dated logs.
- Root JOURNAL.md is the technical development ledger; numbered docs explain behavior.
- Studio control groups use CollapsibleSection. Hide/show existing bodies instead of rebuilding
  widgets; folding must preserve values, model/calibration, active runtime and debug-window state.
- GraphicsWorker exclusively owns Studio renderer mutations, avatar/numeric-debug drawing and
  OpenGL cleanup. Queue operations; keep Tk access on its UI thread and read published status.
- Async draw completion must match source, seek generation and presentation epoch. The UI must
  independently expire displayed live data while graphics is busy; paused inspection is explicit.
- Imported dominant-role lookup is numeric, with immutable head/foot masks cached per asset.
  Static mask caching must not replace dynamic per-observation visibility checks.
- Recorded-input transport is file-only and decoder-thread-owned. Coalesce IPC commands and carry
  seek generations through frames/observations; reject old results without rewriting timestamps.
  EOF releases the worker; timeline restart uses the same immutable file source, not an edited field.
- --render-video is explicit offline file export through a lockstep owned inference child.
  Offline source-relative clocks and zero arrival delay are distinct from live timestamps/latency.
- Video export never overwrites inputs/existing outputs. Verify encoded count/size/FPS and unchanged
  inputs before publishing staged MP4/report/optional PNG; no raw input/audio/landmark output.
- CLI --seconds means source duration for --render-video (default whole remaining file); existing
  --headless smoke checks retain their10s default. Absolute .venv Python works from another base.
- Paused replay is explicitly labelled numeric inspection. Raw preview still expires at600ms;
  live/error/disconnected sources never inherit the frozen-sample exception. Controls stay in Studio.
- Seeks clear native/rig/scale/expression-filter history while preserving completed session facial
  calibration/gains; unfinished capture cancels. Ordinary source changes still discard calibration.
- The avatar renderer accepts only image-free observations. The later private-debug request
  permits a separate UI channel, not camera pixels in rendering or clean output.
- Local inference does not imply network silence. Prebuilt MediaPipe includes usage telemetry;
  upstream says inputs are not sent and provides no official opt-out. See TODO18 and the
  linked maintainer statement; suppressing logs does not disable uploads.
- Raw debug retention is opt-in, paired with observations, cleared on disable/stop and not recorded.
- Camera-auth defaults use ignored Windows-user-encrypted local storage. Never record their values
  in source, documentation, logs, memories or context; UI/env values can override them.
- Inference receives unmirrored input; mirror the complete presentation after geometric rendering.
- Same-frame pose and face inference runs in the child; expressions bypass motion smoothing.
  Optional face-response shaping modifies only presentation, not raw diagnostics or meters.

## Gotchas

- Prior inferred-depth and hood-marker experiments are cautionary history, not reliable body tracking.
- Face detail decreases with whole-body framing; cropping improves detector framing, not real detail.
- No camera endpoint/credentials are bundled. Use explicit runtime configuration, never recovered
  credentials or a guessed LAN address.
- Demonstration animation and public-fixture inference do not prove the owner's live setup.
- Pose segmentation can be HxWx1; normalize only the singleton channel explicitly.
- Native model cleanup is asynchronous relative to terminal status; tests must await worker exit,
  not assume a fixed sleep means the device/models are released.
- Two rendered windows can exhaust the frame budget. Keep a minimum Tk event-loop yield;
  1ms redraw retries previously starved update/input, fixed with an8ms floor and bounded UI checks.
- UI evidence must capture the test application's HWND, not a screen rectangle that can show
  unrelated desktop content. tools\ui_capture.py checks desktop availability and rejects zero
  handles; inspect actual images before promotion. Tests construct Studio with empty private fields.
- Timed native UI fixtures must produce authored observations independently of root.update;
  UI-coupled input can miss calibration sample minima or expire raw previews. Do not weaken
  real freshness, sample or watchdog requirements to compensate for a test producer.
- Async native tests must wait for graphics completion, not merely import commit or inference arrival.
  Await errors from each future; checking done twice can lose a failure that completes between checks.
- Model review must distinguish importer validity, detector availability and visual approval.
  A complete video/report cannot certify perfect rigging; preserve revision hashes and fixed inputs.
- glTF zero-initialized and sparse accessors occur in real Blender exports; do not reject the
  former as absent data. Verify inverse binds against default geometry before committing an asset.

## Context-offload protocol

Read this store on resume, use Context Mesh to resolve bases, and leave siblings read-only.
Update state/journal at milestones, preserve an exact ISO-8601 offload marker, and refresh mesh.
Be honest, concise and English/Latin-script only. No credentials, media or biometric records.
