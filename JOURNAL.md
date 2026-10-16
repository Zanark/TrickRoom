# Development journal

Newest entries first. Record decisions, failures, changes and evidence, not just completed features.
Times use Asia/Kolkata. Raw camera media, source addresses and credentials do not belong here.

## 2026-10-16 - Timeline redraw rate cut, and the ghost camera checked on real tracking

- Owner reported the bottom playback bar flickering during video playback, and asked for the
  ghost camera to be checked against their actual recording rather than the scripted demo.
- Measured the timeline before changing anything, because the obvious explanations were wrong.
  The slider position is monotonic with zero backward jumps; button text, slider enabled state,
  timeline visibility and capture state produce zero flips over 529 samples; and every layout
  dimension including the bar's position and height is completely static. The flicker is not
  state churn and not layout oscillation.
- What is real: _update_playback writes the slider variable on every tick, about sixty times a
  second, while the thumb only advances a pixel or so per second. Each write redraws the scale
  while the avatar is competing for the same UI thread. The position is now quantised to the
  thumb's own pixel resolution and written only when it would land somewhere new, and the time
  label likewise only when its text changes. Writes fall from one per tick to 107 per ten
  seconds, which is exactly the 786px slider times ten seconds of a 73.44s recording. Playback
  still advances correctly at 10.01s per ten seconds.
- Where the slider width cannot be read, as in harnesses that use a mock widget, the old
  every-tick behaviour is kept rather than guessing a resolution. Ten timeline tests caught that
  case before it could ship.
- Ghost camera verified against the supplied recording with live inference running and the
  owner's own model loaded. Shoulder span across the screen measures +49.2px from the front,
  +37.5 at a quarter turn, exactly 0.0 side on, and -52.9 from behind. Zero means the shoulders
  are edge on and the negative value means the character is being seen from the back, so the
  pose does not follow the camera. A separate check confirmed the character's world forward
  stays [0,0,-1] at every camera yaw, which is structural: evaluate() takes no camera argument.
- 522tests, no failures, errors or skips; Ruff and tools\check_docs.py pass; native replay
  timeline and Studio checks pass. No source recording, model or profile was modified.

## 2026-10-16 - Stage clicks reach the camera, and yaw is no longer cut short

- Owner reported that clicking the preview did nothing. The cause was a binding on the wrong
  widget: the stage label is packed fill/expand inside its frame, so it covers the frame entirely
  and every pointer event lands on the label. Binding the frame alone could never fire.
- The focused tests could not have caught this. They inject look deltas straight into the camera
  and never touch a widget, so they passed while the feature was unreachable. Added
  tools\check_ghost_input.py, which generates genuine Tk Button-1 and Motion events instead.
- Also fixed the limitation recorded in the previous entry rather than leaving it documented.
  The pointer is now warped back to the middle of the stage after each motion event and the
  returning event is ignored, so turning never runs out of room. Measured9600px of pointer travel
  across a1017px stage accumulating633.6degrees, more than a full circle and exactly the travel
  times the0.066degrees-per-count sensitivity. Before this the cursor left the stage after about
  eight events and the camera stopped.
- Checked through the real window: click captures, motion turns, pitch clamps at89degrees, Esc
  releases without disconnecting, and no Tk callback errors occur.
- One of my own thresholds was wrong first time round:60events of60px cannot reach a full circle
  at this sensitivity, and the237.6degrees it did produce was exactly correct. The threshold was
  raised rather than the sensitivity being quietly changed to make the check pass.

## 2026-10-16 - A personal model can be the default without hard-coding its path

- Owner asked for a specific exported character to load by default. Hard-coding that path would
  put a private location into source and contradict the existing rule that selections stay
  session-only and are never written into settings, so TRICKROOM_AVATAR follows the pattern
  already used by TRICKROOM_MODELS and the camera variables.
- An explicit --avatar always wins. Unset or blank means the built-in character. A sidecar
  .trickroom.json beside the model is picked up automatically, and an explicit --avatar-profile is
  never overwritten. A configured path that no longer resolves raises naming the variable and the
  path rather than falling back silently, because a silent fallback to the built-in character
  would look like the model failing to load.
- The default is applied to video export as well as the studio and headless paths.
- Verified with the owner's actual export: it validates as profile1 with13985vertices,6406
  triangles and no warnings, and with the variable set a demo run loaded it and rendered73frames
  with bones TRACKED. 11focused cases cover unset, blank, sidecar discovery, explicit overrides,
  a stale path and a directory.
- No model path, private location or asset was added to the repository.

## 2026-10-16 - Ghost camera is flyable from Studio section 08

- Added the control the previous entry was missing: section08 with an enable toggle,
  click-to-capture pointer look, WASD, Q/E and Space/Ctrl, Shift precision, field-of-view and
  speed sliders, reset and a live pose readout. Esc releases the pointer before it disconnects,
  so flying never costs the source.
- Input is collected in Studio and handed to the camera as an abstract command rather than read
  inside it. A focused entry or scale simply stops producing movement, which is why typing in the
  source field cannot fly the camera.
- Verified through a real Studio window, not only unit tests: W moved1.554m forward, D moved
  0.810m right, mouse look reached yaw9.9/pitch-2.6, the field-of-view control took effect at
  35degrees, reset returned to the start pose and released capture, and no Tk callback errors
  occurred.
- Two genuine defects surfaced during validation. Mouse look was being swallowed on a zero-length
  frame: update returned early on dt==0 after the caller had already cleared the pending delta.
  Look is a displacement and must not depend on frame time, so it is now applied before that gate.
  release_pointer also touched preview_frame unguarded, which broke harnesses that build a Studio
  with only the fields they need. One of my own test expectations was wrong as well, comparing
  absolute height against zero when the camera starts at1.65m eye height.
- 511tests, no failures, errors or skips; Ruff and tools\check_docs.py pass. Native Studio passes
  with the extra section; panel heights move to819/2479/312px and the collapsed layout still fits
  the1020x720 minimum. Model studio and the six-angle end-to-end check still pass.
- Unchanged limits: imported GLBs only, because the built-in character is posed from image-space
  landmarks and has no real depth. Orbit and attached modes have no subject wired. Near-plane
  triangles are dropped rather than split. The viewpoint cannot improve a monocular pose estimate.

## 2026-10-16 - Ghost camera renders the stage from any viewpoint

- Owner asked for a movable camera, separate from the capture camera, to take shots from any
  angle. Researched replay and spectator systems against primary source first: Quake's GPL tree
  and Source SDK2013, not recollection. The governing principle is that a replay records
  authoritative state and the camera is a reconstructable view over it, never part of it. Quake
  writes recorded view angles beside the network message rather than inside it.
- Key finding before writing anything: TrickRoom had no camera at all. The shader maps pixel
  coordinates straight to clip space, placement was a uniform scale plus a translation, and the
  room was a cached background. The stage was 2.5D, so this was not a control to bolt on.
- The renderer still has no view stage and did not need one. project_to_screen takes world metres
  through view and projection, divides, and returns pixels plus view-space depth. That depth feeds
  the existing depth buffer, so the rasteriser never learns a camera exists. The room already
  defined its five surfaces in world coordinates, so camera_room reuses them unchanged.
- Borrowed deliberately, with reasons recorded in docs\17-ghost-camera.md: modes are named rather
  than numbered because Valve's own enum shifted ROAMING from6to7; movement is noclip; forward
  follows the look vector while vertical stays world-up; the wish velocity is clamped before
  acceleration so diagonals keep their direction; the modifier halves speed for precision.
- Verified end to end. One identical pose rendered from front, three-quarter, side, behind, low
  and high drew all606triangles in every shot, every pair of images differs, exit0. Subject
  pixels vary as a silhouette should,16070from the side against33975from behind, and the high
  shot foreshortens to233px against about394px level.
- 493tests, no failures, errors or skips; Ruff and tools\check_docs.py pass. Native Studio still
  passes19groups with no callback errors and the CLI demo still exits0, so the room refactor did
  not regress the application.
- Two real defects were caught by validating rather than assuming. Position was integrated by the
  end-of-step velocity, leaving movement frame-rate dependent by about three percent between15and
  120fps; it now uses the analytic integral of the exponential approach and agrees to1e-9. Two of
  my own test expectations were also wrong: wrap_yaw(540) is-180 in a half-open range, and a dolly
  zoom moving closer must widen the angle rather than narrow it.
- Honest limits. There is no Studio button or pointer capture yet, so this is reachable from
  tools\check_ghost_camera.py and not from the application. Only imported rigs can be viewed
  off-axis; the built-in character is posed from image-space landmarks and has no real depth.
  Near-plane triangles are dropped rather than split. None of this improves a monocular pose
  estimate: a front view hides depth error that a steep angle will expose. No camera was opened
  and no raw media or landmarks were written.

## 2026-10-14 - Stage size anchored to a captured base distance

- Owner reported that the scripted demo draws a large character, a recorded source draws a much
  smaller one, and an imported GLB is smaller still. Reproduced and measured rather than assumed:
  demo built-in71.0%of stage height, demo GLB70.0%, the supplied recorded capture22.0%and the
  supplied imported capture21.7%. Both screenshots offered as the target are the same file.
- Root cause is not a defect in the scale filter. presentation.calibration_ratio returns
  median(measured image span / projected posed span) /max(frame_size) and presentation.present
  multiplies max(frame_size) back in, so the drawn size equals apparent pixel size with no
  reference framing. The imported path reads smaller because median bone-span ratios include
  foreshortened limbs, while the built-in character is posed straight from landmark extents.
- room.py already carries a real pinhole camera with focal, 1.65m eye height, a floor plane and
  an inverse floor_point used by the shoe shadows. The character never used any of it; the room
  is a cached background and the figure is placed in image space, so the two only share a frame.
- Added src\trickroom\placement.py: StageAnchor captures the first fully visible body as the
  session base distance, scales later observations by the ratio of spans, and derives a room
  depth from that ratio because apparent size varies with inverse distance. Depth is clamped to
  the room bounds and reports when clamping occurred. The anchor is session-only, resets on a
  source frame-size change or explicit recalibration, and is never written to disk.
- tests\test_stage_anchor.py adds31focused cases: capture, inverse-depth scaling, clamping,
  partial bodies that must not fabricate a placement, reacquisition after loss, frame-size
  changes, explicit reset and invalid configuration. Full suite405tests with no failures,
  errors or skips; Ruff check and format pass.
- Scope is deliberately bounded. The anchor is not yet wired into the imported or built-in
  presentation paths, the character is not yet placed on the floor plane, and no native or
  recorded-source evidence has been produced. TODO28 stays IN_PROGRESS for that work.
- This is a presentation anchor derived from image spans. It is not a measured physical distance,
  a calibrated focal length, a contact estimate or a tracking-accuracy improvement. No camera was
  opened, no model, recording or profile was modified, and nothing was published.
- Also corrected27_HEAD_TRACKING_HANDOVER.todo, which used '## Evidence' and no completion log.
  tools\check_docs.py requires the catalogue headings, so the repository-wide documentation gate
  had been failing since that workstream landed. Its recorded content is unchanged.

## 2026-10-13 - CLI reference-video export completed

- Added explicit --render-video for local recordings: all selected frames, source clock, owned
  inference child, synthetic MP4, aggregate JSON and optional last-frame PNG. No Studio or camera.
  Existing headless smoke defaults remain10wall-clock seconds; export defaults to the whole source.
- Added source start/duration/size and clean-view flags plus matching PowerShell parameters.
  Default JSON is <video-stem>.report.json. Inputs/existing outputs are protected; staged files are
  decoded/verified and published exclusively, with owned-link rollback and failed-export cleanup.
- Real cross-directory short export:91frames/3.025367seconds. Full reference using a stable local
  snapshot of the evolving model/profile:2209frames/73.439941seconds, zero skips, worker exit0.
  Processing took208.84seconds; encoding preserves source duration independently of elapsed work.
- Full availability counts remain881full/1256partial/72not-found body and1546face-present frames.
  These match prior exhaustive counts, not an accuracy/perfection label. Full model hash:
  bb5797ab7e4f5cc4134585344643c2199428aa7f5f70bcd23b54eb4cb684a7a9.
- Actual PowerShell clean/unmirrored four-frame export and default report verified. Full/short MP4
  hashes/frame counts read back; short PNG and nine encoded synthetic frames inspected. No source
  audio, raw images, landmarks or personal calibration persisted.
-374full-suite/37focused cases and Ruff pass. One focused run hit the existing2searly-stop test
  budget; retained its XML and obtained unchanged serial passes. No production safety bound relaxed.
  A readback initially assumed the wrong launcher report name; corrected to its documented default.
- Concurrent retarget.py/test_rig_twist.py changes were preserved and are included in the tested
  tree, not attributed to this feature. The full run preceded additive JSON settings metadata;
  the final metadata fields were then verified through the real launcher export.
- SDK Clearcut warnings recurred; no telemetry setting or network-silence claim changed.
- TODO26 complete. Other-chat guide:docs\16-cli-video-rendering.md. Handbook83pages/181citations
  rebuilt and HTML checked. Receipt:docs\evidence\cli-video-export-validation.json. No publication.
- Final scoped readback confirms all33packaged runtime/resource files, launcher sharing-copy
  equality and book manifests. Repository-wide aggregate refresh is blocked by the independently
  written27_HEAD_TRACKING_HANDOVER.todo missing required completion headers. Its content and
  the previous aggregate receipt were preserved; the checker was not bypassed. Concurrent limb
  and CLI tasks both acquired prefix26; use full filenames rather than renumbering completed work.

## 2026-10-13 - Rear-facing head discrepancy corrected at the face-loss handover

- The reported35second comparison shows a rear-facing torso and camera-facing head. A fresh
  isolated-frame retarget gives a rear head, so merely repeating that pose would miss the bug.
- Continuous history reveals a brief near-front facial estimate at34.9706s. At35.0038s face
  tracking is already absent, yet interpolation retains that prior face-specific local head
  rotation against the rear-facing neck. Expression coefficients had already cleared.
- For eligible pose-derived head/eyes on face loss, current local offsets now replace obsolete
  face offsets while the neck/body retain their normal interpolation. Valid observed head turns
  remain independent of shoulders; missing head points are not reactivated.
- New failing-before face-loss/reacquisition tests pass with existing rig tests:56focused cases
  and374full current-suite cases, no failures/errors/skips; targeted Ruff passes.
- Repeated all2209recording frames with identical detections/model and old/new interpolation.
  In502frames with an eligible pose head and no face, stale offsets over one degree fall42to0;
  the35.0038shead heading changes from-3.10degrees to-176.65degrees. Every non-head joint matrix
  is exactly unchanged; independent valid face turns are covered by tests and native cases.
- Four fresh native cases cover rear/front face loss and independent forward/over-shoulder
  turns with clean-output captures. An initial test incorrectly equated pose-head rotation
  with torso rotation, ignoring the authored neck tilt. Its corrected rest-aware expectation
  passes without relaxed tolerances. The initial failed helper log is retained.
- Handbook remains82pages/181source citations with checked bounds; guides and TODO27 updated.
  Receipt:docs\evidence\head-handover-validation.json. This is not a claim that transient face
  detections or monocular body front/back estimates are accurate. Character/GLB/video bytes
  remain unchanged. No raw frames or landmark arrays were saved, and no physical camera
  was opened. Restart an old app instance; reloading a GLB alone does not reload Python.

## 2026-10-13 - CLI model-review video export requested

- Existing headless commands provide bounded smoke checks and PNG/report output, not saved video.
  Owner wants another model-authoring chat to render a GLB against a reference recording.
- Adding an explicit offline file-to-video path, not automatic camera recording. All selected
  frames will be processed on source time, with native tracking kept in an owned child and only
  numeric observations passed to rendering. Structural/availability evidence is not visual perfection.
- Observed concurrent retarget.py changes and a new test_rig_twist.py module after the prior sealed
  receipt. Those changes are preserved; this task does not claim authorship of the twist work.

## 2026-10-13 - Imported hip collapse corrected in runtime limb frames

- The current user GLB still showed an hourglass hip after the separate asset repair.
  This task reproduces that failure using the unchanged current GLB and synthetic observations
  made from its own rest joints, with the actual Studio enhanced/world/constrained defaults.
- The solved normal uses cross(end-start, middle-start), equivalent to lower x upper.
  Retargeting used upper x lower for the rest normal. The opposite sign caused a180degree
  thigh-frame error even at rest; the minimum mixed hip-matrix singular value reached0.04127.
- A one-line in-memory diagnostic removes that twist. The runtime repair also aims unconstrained
  joints from their driven ancestor's frame, and retains near-straight plane history relative
  to that frame rather than pinning it to the camera during body turns.
- An initial diagnostic accidentally let Renderer.motion_options restore legacy mode; the
  corrected diagnostic asserts the active options. Existing source/GLB conformance alone did
  not check this live-mode orientation failure. It must not be treated as artistic approval.
- Added failing-before neutral/bent/straight/full-turn/lean/temporal regressions.43focused cases
  and338full-suite tests pass with no skips; targeted Ruff check/format pass.
- All2209frames of the supplied recording use identical detections and unchanged model bytes
  in old/new runtime comparisons. Of2047frames with rendered geometry,1422had a minimum
  hip skin-matrix singular value below0.2before, zero after. The median minimum improves
  from0.102928to0.984393; the repaired minimum over the recording is0.567379.
  This conditions the deformation, not detector accuracy or arbitrary-pose cloth collision.
- Fresh native Studio uses its ordinary enhanced/world/constrained defaults and verifies
  front/quarter/rear/lean matrices within2.26e-8, clean output, bind, all three clips and live
  return. Actual owned-window images and same-video source-free comparison images inspected.
- The82page handbook/179citations and core-motion guide describe the signed plane/body-frame
  behavior. Scoped receipt:docs\evidence\limb-frame-twist-validation.json. TODO26 complete.
  No GLB, source recording, weights, camera settings, private calibration or user's running
  application changed. No raw frames/landmark arrays were written; SDK telemetry remains its
  existing separate limitation. Restart TrickRoom; reloading the same GLB alone is insufficient.

## 2026-10-13 - Studio responsiveness corrected with one graphics owner

- Measured the reported lag, rather than treating drag events as repeated seeks. Before-fix
  queued-event p95 was127.23ms paused/131.85ms playing with GLB, clean and black debug views open.
- Cooperative view scheduling alone still missed the budget. Moving only avatar drawing also
  left numeric debug work blocking Tk. Final design serializes both on one bounded graphics owner;
  Tk services controls, installs completed images and keeps raw debug separate.
- Renderer mutations are queued to the same owner; model readiness waits for graphics commit.
  Immutable status snapshots replace reads of half-updated rendering state. Source/seek epochs
  discard old results, and the independent UI loop clears stale displays even during a slow draw.
  Graphics errors/timeouts initiate explicit shutdown; OpenGL cleanup stays on its owning thread.
- Converted dominant-role membership to numeric lookup and cached read-only head/foot masks.
  Eight deterministic studio/clean before-images match exactly for full/cropped/no-face/stale cases.
- Final queued-event p95 was18.25/20.74ms, repeated at14.89/18.48ms. Each phase delivered all80
  positions and committed exactly one seek. Both runs meet the50ms p95/150ms max input budget.
  These are synthetic Tk-event measurements in actual windows, not physical-input or sensor latency.
-312tests pass without skips; Ruff and native Studio/model/motion/debug19/9/10/9 plus timeline7/8
  groups pass. A model-import helper initially awaited commit, not its first rendered frame; its
  bounded wait now checks the actual result. Win32 message injection did not reliably synthesize
  a Tk drag, so the benchmark uses an explicit background-timestamped Tk event queue.
- One full suite concurrent with book rendering hit the existing2searly-stop test budget.
  Retained its XML; the isolated case and serial312-test suite passed unchanged. Production
  tracking/freshness/shutdown thresholds were not relaxed.
- Supplied recording/model/profile unchanged; active seeks still use the same tracking child and
  exit cleanly. Raw preview off, no source media/landmark export, no live camera or publication.
- TODO25 complete. Guides and82page/179citation book rebuilt; scoped evidence is
  docs\evidence\studio-responsiveness-validation.json. Old aggregate and failed approaches preserved.
  Rendering FPS, detector accuracy, earlier native DLL faults and SDK telemetry remain separate limits.

## 2026-10-13 - Studio lag reported; redraw bottleneck measured

- Owner reports UI lag, particularly while dragging the playback timeline.
- The drag handler already postpones seeking until release. Studio instead renders its main,
  clean and debug views synchronously in one callback, delaying native control events.
- Profiled the supplied GLB with authored poses, not new camera input: paired main/clean redraw
  median111.51ms/p95153.08ms under cProfile. Repeated object-array membership/mesh masks, batch
  construction, shadows and graphics readback contribute. These are instrumented measurements.
- TODO25 tracks queued native input latency, cooperative view redraws, equivalent static mesh
  caching and regressions. Source recording/model remain read-only; live testing stays paused.

## 2026-10-13 - Recorded-video timeline completed after chat retry

- Resumed saved work after the chat's400failure; no application rollback or source loss was inferred.
  Fixed the native helper's loop-variable closure warning and finished the playback acceptance.
- The Studio-only bottom bar supports play/pause, elapsed/duration, click/drag on release and
  Left/Right/Home/End seeking. It never enters clean output and is hidden for live/demo input.
- Capture alone owns the decoder; coalesced commands and seek generations discard old results.
  Seeks recreate native tracking and reset presentation history, preserving completed face
  calibration/gains. Paused numeric samples are labelled; raw input still expires normally.
-288full-suite tests pass with no skips. Native timeline groups pass7generated/8including the
  supplied recording; general Studio/model/motion/debug groups pass19/9/10/9. Ruff check/format pass.
- The first native Pause probe did not acknowledge the action; the helper now waits for UI control
  readiness. Motion calibration initially missed the minimum sample count, including at minimum
  window size. Debug reopen also saw its authored input expire. Both old test producers depended
  on Tk pumping, unlike real input. Independent bounded producers fixed the fixtures without
  lowering sample requirements, extending freshness or disabling watchdogs.
- The supplied recording and GLB were exercised at requested18/30/18seconds, observed at
  17.9861588/29.9880133/17.9861588seconds.41frames inferred; same worker for active seeks, exit0
  and no forced shutdown. Original recording/model/profile unchanged; raw preview stayed off.
  This is bounded transport/presentation evidence, not exhaustive motion or accuracy qualification.
- Inspected actual generated and supplied-model Studio captures plus changed handbook pages56/62.
  Maintained guides/book updated:82pages,177resolved citations, no blank/overflow pages and
  passing offline HTML. Rebuilt wheel matches all31runtime/resource files.
- TODO24 complete. Sanitized receipt:docs\evidence\replay-timeline-validation.json; prior aggregate
  archived before replacement. Current-base continuity is updated; no live camera, source-media
  exports, credential changes, sibling edits, commit or publication.

## 2026-10-13 - Recorded-video timeline implementation underway

- Added a bottom Studio bar and file-only transport commands. Decode/inference timestamps remain
  monotonic and separate from media time; seek generations invalidate old samples and raw previews.
- Capture retains exclusive decoder ownership. IPC commands coalesce rather than queuing every drag.
  Seeking recreates the native tracker in its owned child and clears rig/scale/filter history.
- Explicitly paused replay may show labelled frozen numeric samples; raw preview still expires.
  Completed session facial calibration survives seeks; in-progress collection is cancelled.
- EOF keeps normal finite worker cleanup. Timeline restart uses the same recording, never the
  editable source field or a previous live endpoint. Native behavior and edge cases are being tested.
- Initial focused run found five mock-constructor incompatibilities with the new keyword arguments;
  the fixture was updated. These were test-harness failures, not completed timeline acceptance.

## 2026-10-13 00:30 +05:30 - Collapsible control sections implemented

- All seven numbered right-panel sections now share a collapsible container. Input starts open,
  others folded; Expand all/Collapse all stay above the scrollable region.
- Controls are hidden/shown, not destroyed. Values, calibration, model selection and runtime
  survive folding; private debug windows require their own explicit close/toggle.
- Added Space/Enter activation, Tab-focus handling, collapse-all scroll reset and compact-layout
  checks. Initial39focused cases and native checks passed; panel heights were2088pxexpanded,
  780pxdefault and273pxfully collapsed, with all headers fitting the minimum window.
-19native studio groups and9model groups now pass, including hidden-control Tab traversal and
  preserving separate debug windows. Default/all-collapsed layouts were visually inspected.
- Updated documentation, native previews and scoped evidence; TODO23 is complete. No real camera,
  user recording, avatar asset or tracking/rig algorithm was changed or opened.

## 2026-10-12 23:44 +05:30 - Scale correction resumed after PC shutdown

- Confirmed the saved implementation, full2209-frame comparison, baseline archive and supplied
  model/video hashes survived unchanged. The complete before/after run had finished before shutdown.
- Repeated59focused regressions successfully. A post-restart normal runtime check processed201
  frames over28seconds and shut down cleanly with no forced worker termination. The synthetic output
  has corrected framing. High frame skipping/low display throughput is not a performance pass.
- Retained two earlier integrated failures rather than replacing their results with success.
  One retry measured89smodel loading before its playback window expired; root cause is unknown.
- At18seconds, ongoing corrected scale0.305634matches a fresh-start0.303491instead of retaining
  the old1.460235. All four sampled full-body checkpoints agree within3.8%.
- Completing handbook, documentation and package/evidence readback. Original GLB/profile/video
  stay read-only; no live source, private screenshot, raw/landmark export or system setting change.
- Completion follow-up: TODO22 is DONE. The rebuilt handbook remains82pages/175citations with
  updated automatic-framing guidance and inspected scale pages. Wheel/runtime bytes and all
  nine saved comparison-image hashes agree. Earlier failed startup checks remain recorded.

## 2026-10-12 - Imported-avatar zoom mismatch reproduced and corrected in placement

- Inspected the supplied GLB and compared both avatar paths on the same recording.
  Model height is approximately1.81authored units, with plausible limb lengths; it is not
  evidence of a gross unit/export error.
- Reproduced the importer locking its first scale at2.128s/14eligible joints/partial body.
  The saved value1.460235 remained even when full-body estimates were2-4times smaller.
  The old formula additionally counted inferred depth as if it were screen size.
- Replaced the latch with one smoothed uniform scale from eligible projected2D spans.
  A three-span quorum, projection conditioning, observation-key deduplication and reset/expiry
  rules prevent startup history or extra display windows from controlling size indefinitely.
-59focused regressions pass. Complete-recording comparison and native validation are underway;
  no source model/profile/video edits or live-camera reconnection. The user's no-question window
  is being honored; their running application is not interrupted.

## 2026-10-12 20:25 +05:30 - Recorded-source test view added

- Added Test from video and Replay last video beside the scripted demo controls. Selection uses
  the existing isolated file replay, retains only the session path, and preserves the avatar.
  Imported bind/clip previews switch to tracking mode so recorded motion actually drives them.
- Video replay is now labelled separately in the studio, head detail, stage and clean output.
  Raw preview remains opt-in; no live source is opened or interrupted by the new action.
- Final53focused cases,14native studio groups and9model groups passed. A bounded check on the supplied
  recording exercised125inferred frames through built-in/GLB stages, clean output and both
  black diagnostics, with no callback errors, raw/landmark exports or source modifications.
- This request adds an accessible test view; it does not change tracking, rigging or artistic
  acceptance. TODO21 is complete; guides, source citations and verified UI previews are updated.
  Test-module names now accompany aggregate unit counts to distinguish targeted from full runs.
- Handbook remains82pages/175source citations; updated pages were visually inspected. Runtime
  wheel bytes,79source/resource digests and refreshed preview/document hashes match.

## 2026-10-12 15:11 +05:30 - First core motion upgrade completed locally

- Owned spawned inference now contains native-worker failures with bounded IPC/watchdogs,
  Windows job cleanup and a separately paired opt-in raw preview. Face debug uses licensed
  static topology rather than importing MediaPipe in Studio. SDK telemetry itself is unchanged.
- Imported rigs use separately filtered world directions, authored lengths, optional bounded
  two-bone posing, arrival-adjusted interpolation and explicit tracked/held/returning/rest states.
  Strict visibility remains default; total loss and600ms source staleness still clear geometry.
- Face response offers explicit in-memory neutral/range calibration, per-channel gains and
  immediate independent blinks. Detector observations/diagnostics are not replaced by presentation.
-199tests/no skips; twelve studio/nine model/nine debug/ten new motion native groups passed.
  A too-short fixed UI calibration wait was replaced with a bounded completion-condition wait.
  Delayed-arrival interpolation and honest held/rest HUD labels were corrected during review.
- Final isolated recording decoded2209/inferred1851/skipped358, EOF/exit0 without forced shutdown.
  Every-frame comparison completed2209/2209; raw detection counts matched the first test exactly,
  authored-length error below2e-8, and2047intervals had actual interpolated rig poses.
  Enhanced rendering costs more:mean/p95 16.13/21.56ms versus12.16/16.16ms legacy in this diagnostic.
- Inspected synthetic comparisons and native UI. Initial close-up scale may require explicit
  full-body recalibration; optional rest is the authored rest pose, not a polished idle animation.
- Updated guides, source map, TODO20 and handbook:82A5pages/35chapters/175source citations,
  valid offline HTML and diagram renders. Wheel includes the worker and licensed topology resources.
- Visual book review caught a citation-only overflow page; condensed the affected chapter and
  removed redundant references. Refreshed the earlier slate-room technical figures to green.
- No live camera, original-video modification, raw/landmark export, personal calibration file,
  final-art rig, optional OpenSeeFace/VMC/spring integration, commit, push or publication.

## 2026-10-12 14:06-14:28 +05:30 - Core motion implementation authorized and underway

- Owner explicitly authorized starting implementation. The first integrated delivery covers
  reliability, world-space rig motion, interpolation/loss handling, constrained limbs and face
  response. Optional tracker/protocol/simulation integrations remain separate later work.
- Archived the previous66 source/tool files and receipt without private inputs or credentials.
- Implemented spawned camera/model ownership with request/response snapshots, a separate opt-in
  raw-preview path, crash/watchdog reporting and Windows kill-on-close job ownership.
- Added world-coordinate eligibility/filtering, rest-aware constrained two-bone posing, bounded
  pose history, source-stale clearing and explicit held/returning/rest presentation states.
- Added session-only neutral/range facial response, independent blink endpoints and per-channel
  gains. Original observations and diagnostic counters are not replaced by presented poses.
-56focused cases passed. UI/CLI controls are now wired; native integration/replay verification,
  packaged face-topology isolation and documentation remain in progress. No live camera resumed.

## 2026-10-12 - VSeeFace tracking and rigging research completed

- Read the official VSeeFace site/manual, release history, SDK documentation and English
  interface strings; traced pinned OpenSeeFace Python tracking and public C# animation code.
- Native webcam tracking is facial; hands normally use Leap Motion, and full-body sources can
  enter over VMC. RootMotion's author describes limited-target VRIK as an analytic/heuristic
  pose solution, not perfect measurement. Public code is not the entire closed application.
- Traced neutral calibration, fit/outlier rejection, interpolation, blink/gaze remapping,
  facial composition, hand acquisition/loss weights, spring update ordering and child-process cleanup.
- Release-note reconciliation avoided stale claims: later iFacialMocap reception accepts
  partial shapes and translates for non-Perfect-Sync rigs; all52controls concern full fidelity.
- Compared the actual Python pipeline. World pose is captured but not consumed by current
  GLB retargeting; image-space directions are used. The GLB path already preserves bone lengths,
  while the built-in procedural parts use measured lengths and omit unavailable regions.
- Delivered docs\14-vseeface-research.md with two diagrams, pinned sources, code citations,
  priority table, test methodology and licensing/privacy limitations. TODO19 is complete.
- No application code, dependency, model, live camera, private-video reprocessing, SDK installation,
  firewall/proxy setting, commit or publication. All proposed changes await a separate request.

## 2026-10-12 03:44 +05:30 - First supplied-recording test completed

- Owner authorized testing the supplied video, not resuming the live camera or applying fixes.
  Input was read-only; no raw frames, audio or landmark arrays were saved.
- Unmodified normal playback reached EOF with2209decoded/2191inferred/18skipped frames,
  exit0 and clean shutdown. The earlier native startup crash was not reproduced; no fix is claimed.
- A private synchronous diagnostic processed every one of2209frames, exercising default tracking,
  smoothing, avatar rendering and black skeleton/face debug rendering. All returned without
  exceptions, and the original file hash was unchanged.
- Pose-present96.74%, full required skeleton39.88%, partial56.86%, face69.99%. Both blinks,
  jaw, smile and head-angle signals activated. Availability/activation is not gesture accuracy.
  No jump exceeded the explicit12%-diagonal heuristic, which does not prove jitter-free motion.
- Reviewed nine synthetic-only samples. They show full characters in some portions and
  head-only/partial output in others. Raw-video ground truth was not manually compared, so
  deliberate close-ups/cropping and actual detection errors are not yet distinguished.
- Private reports, diagnostic harness, failure intervals and contact sheet:
  .local\video-checks\20261012-first. No application code was changed.
- Native MediaPipe emitted Clearcut usage-telemetry warnings. Verified upstream collaborator
  statement in google-ai-edge/mediapipe#6291: no official opt-out; they say input data is never
  sent. This is not an independent packet-content audit or a network-silence guarantee.
  Created future workstream18; no dependency, firewall or proxy changes made.
- First test is complete. Await the next requested action; live-source testing stays paused.

## 2026-10-12 - Live smoke checks paused; recorded video will be supplied

- The owner supplied a live endpoint for testing. Reused encrypted local authentication without
  persisting the address/values or saving camera images, video or landmarks.
- Capture-only received30frames at1920x1080 with no reconnects and clean shutdown. A12second
  tracking-only run processed285frames, with277pose-present and9face-present results; pose-present
  means at least four eligible points, not confirmed full-body coverage. Renderer-only demo passed.
- Combined headless startup crashed twice. Windows reported WINHTTP.dll/c0000409 for the first;
  the diagnostic repeat emittedc000070a during rendering/resizing and MediaPipe initialization.
  This is a reproducible integration failure, not a proven bad URL or established DLL root cause.
- The owner then explicitly paused testing and will supply a video. Stopped the remaining
  sequential-startup probe and fault-metadata command; no outcome from that probe is accepted.
  No code fix was applied. Future work must use the supplied recording or fresh explicit direction,
  not automatically reconnect to the live camera.
- Workstream07 remains blocked/paused. Existing theme, model support and handbook work stay complete.

## 2026-10-12 03:02 +05:30 - Green wireframe room completed locally

- Near-black green panels, vivid thin green grids/borders and no calibration crosses now follow
  the supplied theme. Character geometry, perspective, shadows, tracking and privacy remain unchanged.
- 169 tests/no skips, twelve native studio groups and nine imported-model groups passed.
  Landscape, portrait, empty, clean output and both native model paths were visually inspected.
- An initial rectangular desktop capture returned the lock screen instead of the app; that image
  was discarded. Shared UI capture now targets the test window's HWND, refuses invalid handles,
  and explicitly skips unavailable desktops. Eight regression cases cover the guard/capture path.
  Subsequent actual application captures were inspected before promotion; private fields are empty.
- Refreshed room/main images, GIF and native screenshots. The rebuilt authoring guide remains
  82A5 pages/35chapters/175resolved citations, with valid offline HTML and no layout-bound failures.
- Warm full-render median/p95 is10.11/10.95ms, not camera latency. Older fixture/loopback results
  remain historical rather than being presented as newly executed camera checks.
- TODO17 completed; final-art09, owner-camera07 and interactive10 remain separate. No camera
  session, final model replacement, commit, push or publication was performed.

## 2026-10-12 02:41 +05:30 - Dark green wireframe theme requested

- Inspected the supplied green/black room reference and sampled its panel/line palette.
- Replaced slate panels and pale grid/borders with near-black green surfaces and vivid green lines.
- Removed calibration cross markers for the cleaner supplied style. Existing perspective,
  character, shadows, controls and camera/debug privacy behavior remain unchanged.
- Source image preserved privately with SHA256 in the room guide and TODO17.

## 2026-10-12 02:29 +05:30 - Private debug windows and encrypted defaults complete

- Added independent default-off raw input, black skeleton and connected black face-mesh windows.
  They use input orientation, never enter avatar/clean output, and do not fake detected points
  from the scripted avatar. Raw frames are read-only, paired atomically and released when stale/off.
-159tests/no skips and nine native debug lifecycle groups passed, including concurrent clean
  output, close/reopen, disconnect and no retained raw frame after disable/stop.
- Actual public-fixture MediaPipe output produced33pose/478face points and1322unique edges;
  black diagnostics inspected without saving raw input.
- Local requested auth defaults are Windows-user-encrypted and ignored by Git. A real UI check
  verified default prefill/password masking without printing or recording the values.
- Updated privacy guides, TODO16 and the Blender handbook; final handbook remains82pages with
  validated source citations and self-contained HTML. No owner-camera access or personal recording.

## 2026-10-12 02:20 +05:30 - Explicit private debug views and local defaults added

- User authorized three default-off diagnostic windows: raw processed input, skeleton on black,
  and connected facial landmarks on black. The raw window is a deliberate exception outside
  the synthetic avatar/clean-output path, not a change to exported output privacy.
- Runtime retains one read-only input copy only while requested, publishes it with the matching
  observation, and releases it on disable/stop/staleness. Debug coordinates stay unmirrored.
- Native synthetic checks passed all three-window/close/reopen/disconnect/clean-output cases.
  Actual MediaPipe on the cached public fixture yielded33pose points,478face points and1322
  unique tessellation edges; only black numeric views were saved, not raw input.
- Requested authentication defaults were configured and verified with Windows user-bound
  encryption in ignored local storage. Values are intentionally omitted from source, docs,
  logs and context. Environment/session field overrides remain available.
- Full regression suite reached158passing cases before the final stale-copy expiry regression.
  Documentation and the authoring handbook are being reconciled with the explicit debug exception.

## 2026-10-12 01:42 +05:30 - Blender pipeline and82page authoring handbook delivered locally

- Implemented Profile1 self-contained GLB import, bounded validation, custom name mappings,
  inverse-bind skinning, morph-before-skin expressions, texture/sampler/alpha-mask rendering,
  LINEAR/STEP clip previews, fixed-length FK body/head/hand/eye posing and scale calibration.
- Studio/CLI support validated model loading, bind/clip/live modes, reports, recalibration,
  invalid-import retention, built-in return and bounded cleanup. No direct.blend evaluation,
  full finger capture, IK foot locking, cloth/physics or unsupported PBR/compression promise.
- Actual Blender4.5.14 created/exported two original technical rigs. Runtime vertex comparison
  max errors2.2469e-7 wave and5.8990e-8 face; eye-bone mode moved bound vertices0.01051 units.
  Source preflight/export helper reproduced the GLB hash without resaving the source.blend.
-148tests passed with no skips. Original12native groups and9model lifecycle groups passed.
  A later native model check exposed redraw starvation while rendering two windows with a1ms
  retry floor; a40s diagnostic timeout captured the active tick/update path. Raising the minimum
  event-loop yield to8ms corrected the repeat without coupling inference to UI timing.
- Final imported-model loopback:57received/48inferred,48body+face,7skipped and pending work at
  sample boundary; mean render9.05ms/inference36.55ms, age63.06/66.44msmean/p95. Startup is
  included; this is not owner-camera or physical exposure-to-display evidence.
- Delivered82A5-page PDF,35chapters/workshops,13249word tokens,175resolved source citations,
  two local Mermaid diagrams and original technical screenshots; no blank/out-of-bounds text.
  Offline HTML35headings/8embedded decoded figures, no external images or horizontal overflow.
  Print cover/body/diagram/table/code/workshop pages and browser layout inspected.
- Book sources/edition manifest are under docs\book; PDF at docs\TrickRoom-Blender-Authoring-Handbook.pdf.
  Workstreams13-15 complete. Final reference-art character09, actual camera07 and interactive
  physics10 remain separate. No owner data/camera access, commit, push, publication or art approval.

## 2026-10-12 - Blender support verified and authoring handbook in production

- Real Blender exports now load with23mapped bones,12shape keys, embedded texture and two clips.
  An alternate exported eye-bone fixture validates the optional gaze mode.
- Compared runtime vertices directly to Blender-evaluated source geometry: maximum errors
  2.25e-7 for the wave and5.90e-8 for the facial clip. Source preflight/export reproduced the GLB hash.
-147tests passed at the implementation checkpoint; native model load/clip/recalibration/rejection/
  fallback/shutdown checks and imported-model MJPEG rendering also passed.
- Corrected zero-initialized glTF accessors after observing them in the actual export; the reader
  now handles both sparse and implicit-zero forms. Added bind-rest consistency and effective-eye
  binding checks instead of treating names alone as proof of animation support.
- The first book build produced71A5 pages, no blank pages or out-of-bounds text, with150 resolved
  source citations. Practical modeling/weighting/shape/export workshops are being added before
  final publication of the local edition. No final-art character or owner-camera qualification claimed.

## 2026-10-11 23:49 +05:30 - Blender interoperability and detailed handbook requested

- Owner requested actual Blender model readiness first, then a detailed50-100page authoring/rigging
  document explaining exactly what the runtime needs. This authorizes the new import/animation
  pipeline; it is not a request to replace the accepted reference-art direction with a test model.
- Chose self-contained GLB2.0, versioned optional bone/shape mapping, standard skinning/morphs,
  embedded PNG/JPEG base color, OPAQUE/MASK, and LINEAR/STEP clip previews with explicit rejection
  of unsupported Blender/render features. No arbitrary.blend runtime evaluation is promised.
- Verified Blender4.5.14 and its actual glTF exporter options, plus official Blender/Khronos
  material, coordinate, skinning and animation guidance.
- Runtime import/retarget modules are being implemented. A separate original technical rig
  will be exported by Blender and exercised before the handbook is authored.

## 2026-10-11 23:33 +05:30 - Perspective lab complete locally

- Delivered the projected floor, ceiling, side walls and back wall with coherent grid/cross markers,
  per-plane shading, immutable bounded caching and subtle floor-clipped shoe shadows.
- Existing reference character, inputs, pose/face controls and unavailable-joint behavior preserved.
  The room toggle, clean output, portrait/wide framing and stale/partial states were inspected.
- 107 tests passed with no skips; twelve native UI groups passed without callback errors.
  The initial ultra-wide floor-percentage test was corrected to the actual projection invariant,
  not by distorting the room to satisfy an arbitrary coverage percentage.
- Fresh actual-model cases and same-session motion/loss/reacquisition passed. Final30Hz loopback:
  117received/116inferred,116body+face,one skipped sequence,30.17msmean inference,
  15.46msmean rendering,55.82/87.22msmean/p95postdecodeage; all workers shut down.
- Room-gallery warmed median/p95 full rendering11.03/12.25ms. Static room caches do not grow
  without bound; tests check immutability, clipping and exact presentation-only mirroring.
- Refreshed room/main/character galleries, native screenshot, guides, source map and TODO12.
  Previous character-only receipt is preserved separately. No camera, example mannequin,
  physical floor calibration, collision/interactive object, owner approval or publication.

## 2026-10-11 23:13-23:18 +05:30 - Perspective lab requested and implemented

- Inspected both attached examples: white-grid enclosure and slate calibration room. The second
  mannequin is an environment/composition example, not a replacement for the reference character.
- Preserved both images privately with hashes and archived the pre-room character validation.
- Implemented five authored surfaces under one pinhole camera: floor, ceiling, side walls and back,
  with coherent tile spacing, calibration crosses, shading and a bounded read-only image cache.
- Added decorative floor-clipped shadow ellipses from actual eligible rendered shoe bounds.
  These do not measure ground contact, infer missing feet or implement room physics.
- First landscape/portrait/clean/empty views were inspected. Softened the shadow bands and made
  overlap combination order-independent.
- A first test assumed a fixed floor-area percentage even at an extreme1280x240aspect. That was
  not a perspective invariant; replaced it with the projected back-floor width/height lower bound.
- Existing field StageOptions.grid now controls the whole lab; the UI label is Perspective lab room.
  Avatar geometry/tracking stays unchanged; future interactive room objects remain workstream10.

## 2026-10-11 22:57 +05:30 - Reference avatar completed locally

- The dummy now follows both supplied sheets: enlarged tan/angular face, minimal reactive eyes/
  mouth, stepped jaw shading, dark layered hair, beige padded headphones, charcoal hoodie with
  drawstrings/pocket/hood/cuffs, olive cargo pants with flaps and chunky panelled/laced sneakers.
- Authored part geometry follows existing eligible landmark endpoints. No reference photo is
  used as a texture and no camera pixels reach graphics. This is not a skinned Blender rig.
- Contour/skeleton diagnostics remain available and default off to preserve the character's look.
- Multi-angle review drove real fixes: removed painter-order overlaps through an OpenGL depth
  buffer, refined head proportions/fallback scale, jaw patches, rear hair and headphone clearance.
-90tests passed; eleven native UI groups passed without callback errors. Setup/dependencies,
  lint/format, package build and documentation/TODO structure checked.
- Fresh actual-model fixtures, translation/loss/reacquisition and30Hz loopback passed:
  110received/108inferred,108body+face,31.35msmean inference,15.55msmean renderer,51.93/82.02ms
  mean/p95postdecodeage. No phone camera, real human-motion recording or physical latency claim.
- Body/head six-angle sheets, expression sheet and updated motion/loss gallery are delivered;
  authored model count5616triangles includes coplanar color tiles. Warmed renderer median/p95
  9.64/10.84ms on the verified AMD780M/OpenGL3.3 context.
- Original images remain unchanged, private reference copies/hashes are retained, and initial
  mannequin source/gallery/receipt are preserved. No commit, push, publication or owner approval.
- Workstream11 is DONE; live-camera qualification07 remains BLOCKED, Blender09/room10 not started.

## 2026-10-11 22:18 +05:30 - Reference character update started

- Inspected both owner-supplied sheets: full turnarounds, head and headphone close-ups,
  clothing/shoe details, palette blocks and illustrative wireframes.
- Preserved original file hashes, private working copies, prior renderer/gallery and initial evidence.
- Visual target: dark spiky hair, beige over-ear headphones, tan angular face, charcoal hoodie,
  olive cargo pants and cream/taupe sneakers. This is near-final art direction, not a throwaway style.
- Plan: authored low-poly part geometry/materials driven by existing observations; optional debug
  contour/skeleton rather than default colored-stick anatomy. Final Blender rig remains deferred.
- Owner is stepping away and explicitly requested no questions; continue this scoped update autonomously.

### 22:37-22:41 +05:30 - Authored parts and oblique-view correction

- Built complete head/hair/headphone and hoodie/cargo/sneaker part geometry, with deterministic
  object-space color tiles, cloth pockets/cuffs/drawstrings and reactive minimal facial features.
- First software painter-order render ran at roughly11-13ms warm, but the multi-angle review
  exposed striped pocket/skin overlap caused by mean-depth sorting of intersecting triangles.
- Replaced that shortcut with true per-pixel OpenGL depth testing through ModernGL. The new
  dependency is explicit and pinned; verified OpenGL3.3 on the local AMD Radeon780M.
- Checked front/three-quarter/side/back views and six facial states. Refined head proportions,
  jaw shading, rear hair coverage and headphone clearance; no raw camera/media input was involved.
- Existing targeted tracking/render/expression checks passed. Full runtime/gallery/documentation
  reconciliation is still in progress; no owner visual approval is implied.

## 2026-10-11 21:37 +05:30 - Prototype opened for use

- Opened the no-camera demo and verified its native window is responsive.
- The source/models/environment are ready; actual phone input starts only after explicit connection.
- Context handoff ep_782 and Context Mesh registration are complete. No further build/test work
  is pending for this increment; live qualification and future avatar/room work remain separate.

## 2026-10-11 21:29 +05:30 - M1 engineering complete; live qualification remains open

- Delivered Python source, constrained environment, model setup, desktop/CLI launch, body/face
  tracking, fully synthetic stage, clean output window, numbered docs/TODOs and original visuals.
- Final regression suite:70 passed in4.13s, no skips. Ruff check/format, pip consistency,
  documented setup/model verification and local wheel build passed.
- Actual public-fixture run at21:26: five16-frame cases; positive body+face16/16, cropped
  legs correctly partial, side-profile face unavailable, blank state empty. Translation,
  loss and reacquisition passed in the same model session.
- Final30Hz loopback at21:27:112 received/111 inferred,111 body+face, zero skipped sequences,
  27.34ms mean inference,7.18ms mean rendering,45.62/67.12ms mean/p95 postdecode age.
  Shutdown was verified. This is not phone-to-display latency or real motion evidence.
- Expanded native studio check now covers actual inference on a generated blank replay and
  EOF controls. Its first added assertion ran before asynchronous model cleanup completed;
  changed the test to await actual worker exit/control state with a bounded deadline. All ten
  groups then passed without Tk callback errors.
- Added correct cleanup on desktop KeyboardInterrupt, terminal worker failure status,
  control-character source rejection, and Connect re-enabling after replay EOF.
- The public CDN rejected Python urllib with403 for one fixture. Used the already fetched,
  hash-matched public tutorial image; did not change the expected face result or use private media.
- Separated confidence-based eligibility from ground-truth visibility in labels/docs: ML itself
  can infer an incorrect occluded joint. No application-side missing-limb synthesis exists.
- docs/checks cover15Markdown documents,23local links and10workstreams. Synthetic studio,
  six-state gallery and GIF are retained with hashes. Aggregate receipts include an explicitly
  uncommitted source-tree digest, not an invented commit.
- Workstreams01-06 and08 complete;07 remains BLOCKED on actual owner-camera/framing/feedback.
  Blender avatar/rig09 and interactive-room10 remain NOT_STARTED. No final model, virtual-camera
  producer, cloud deployment, commit or push was performed.

## 2026-10-11 21:03 +05:30 - Real-model and UI checks; observed limitations

- Initial unit suite: 60 passed, five failed because the duration tests expected ValueError
  instead of argparse.ArgumentTypeError. Corrected the assertion type; all 65 passed.
- First positive inference exposed this MediaPipe build's HxWx1 segmentation masks.
  Normalized the singleton channel explicitly and added regression coverage.
- Official side-profile pose fixture: 33 visible pose points and one contour, but no face.
  Six independently tested head-crop sizes (64-180 pixels) still did not detect that profile.
  Do not call this universally reliable profile-face tracking.
- The front-facing fitness image referenced by the official Pose tutorial yields 33 pose
  points and an independently tracked face on the same frame. Keep both fixtures:
  the profile exercises pose-only head fallback; the front-facing image exercises expressions.
- Native Tk checks passed all nine initial groups, including controls, invalid input,
  cropped-body status, clean window and close, with no callback errors. Only synthetic demo
  pixels were displayed/captured; no owner camera was opened.
- Inspected the complete synthetic six-state contact sheet and native studio screenshot.

## 2026-10-11 20:59 +05:30 - M1: first integrated runtime and stage

- Implemented bounded MJPEG/device/replay capture, same-frame pose and crop-assisted face inference,
  image-free observation contracts, confidence gates, smoothing and synthetic-only rendering.
- Added a faceted head, expression controls, body contour/skeleton, head-detail panel,
  native connection studio, clean output window and Windows setup/launch commands.
- Fresh isolated environment resolved Python 3.12.10, MediaPipe 0.10.35, OpenCV 5.0.0,
  NumPy 2.5.3 and Pillow 12.3.0. Both official models downloaded and matched pinned SHA256s.
- First one-second bounded demo rendered 30 frames. Inspected its synthetic PNG.
- Actual pose/face models initialized and returned zero joints/no face on a blank image.
  This is negative-input evidence, not a positive camera/tracking qualification.
- Initial inspection exposed mirrored head-detail orientation and potentially mirrored
  partial-body text. Corrected presentation-only mirroring and explicit demo face labels.
- Positive fixtures, network regression tests and native UI checks are next.

## 2026-10-11 20:33 +05:30 - M0: scope and workspace

- Started from the original README: a whole-body VTuber inside an eventual interactive room.
- First milestone is now explicitly body/face tracking and complete synthetic visualization.
  Final character art, Blender rigging and room-object interaction are deferred.
- Selected Python 3.12, MediaPipe Pose/Face Landmarker and a native Tkinter control surface.
  This is an experiment, not a commitment to the eventual renderer or rig format.
- Chose same-frame inference in one worker and a latest-frame capture slot. This avoids mixing
  a face from one capture with a body from another while keeping the UI independent.
- Chose a pose-guided original-resolution face crop to help whole-body camera framing.
  Upscaling is not treated as recovering missing facial detail.
- Chose a synthetic-only renderer boundary. Silhouette masks may supply geometry, never colors.
- Verified numbered TODO index/workstream conventions from existing projects.
- No explicit camera endpoint is available. A launchable connection UI and separately labelled
  demo/fixture validation will be provided; no camera address will be guessed.
