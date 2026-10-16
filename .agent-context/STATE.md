> **Last updated:** 2026-10-16 (Asia/Kolkata) - ghost camera flyable from Studio; stage anchor started; timeline redraw cut.
> **Last context offload:** 2026-10-16T19:55:06+05:30

# TrickRoom state

> Identity: the full-body VTubing engineering and creative-prototyping partner.
> Resume from verified evidence; plans, technical compatibility and artistic approval are different.

## Working location change

Work since 2026-10-14 happens in a Copilot worktree on branch
test-user-copilot-workspace, not directly in this base. The base checkout sits on
agentic/localCopilot, which deliberately tracks .venv, .local, models and node_modules so an
assistant can read previously ignored evidence. That branch must never be pushed: it carries
.local\camera-auth.dpapi and about 858MB. The working branch was reset onto clean origin/main
and keeps every ignore rule active, so none of that can reach a commit from there.

The worktree has no .venv of its own. Run its source with this base's interpreter:
PYTHONPATH=<worktree>\src, TRICKROOM_MODELS=C:\devdesk\homedesk\TrickRoom\models, using
.venv\Scripts\python.exe here. Without PYTHONPATH the editable install silently resolves to this
base's src, so you would test the wrong tree.

Four commits are on that branch and none are pushed: restored ignore rules, the stage base
distance anchor, the ghost camera and its Studio controls, TRICKROOM_AVATAR, and the timeline
redraw fix.

## Current focus

GHOST CAMERA USABLE; 29_GHOST_CAMERA.todo is IN_PROGRESS. Studio section 08 flies the view with
WASD, Q/E or Space/Ctrl, Shift for precision, mouse look, field-of-view and speed sliders, reset
and a pose readout. Esc releases the pointer before it disconnects. Applies to imported GLBs only.

The renderer never had a camera: its shader maps pixel coordinates straight to clip space and the
room was a cached background. No shader change was needed. ghostcam.project_to_screen takes world
metres through view and projection and returns pixels plus view-space depth, which feeds the
existing depth buffer. room.camera_room reuses the room's existing world-space surfaces.

Verified on the supplied recording with live inference and the owner's model: shoulder span
+49.2px front, +37.5 quarter, exactly 0.0 side on, -52.9 behind. The pose cannot follow the
camera because evaluate() takes no camera argument; world forward stays [0,0,-1] at every yaw.
Six-angle offline renders are distinct and populated. Real-window input checked: W moved1.554m,
D moved0.810m, 9600px of pointer travel across a1017px stage gave633.6degrees of yaw.

28_STAGE_BASE_DISTANCE.todo is IN_PROGRESS and only partly built. placement.StageAnchor captures
the first fully visible body as a session base distance and derives depth from span ratios, with
31 tests, but it is NOT wired into either presentation path. Measured before state: demo built-in
71.0% of stage height, demo GLB70.0%, recorded capture22.0%, imported capture21.7%. Root cause is
that calibration_ratio divides by max(frame_size) and present() multiplies it straight back, so
drawn size equals apparent pixel size with no reference framing.

522tests, Ruff and tools\check_docs.py pass. The docs gate had been red since workstream27 landed
because that file used '## Evidence' instead of the required headings; that is now repaired.

## Previous completed milestones

CLI VIDEO EXPORT COMPLETE. 26_CLI_VIDEO_EXPORT.todo is DONE. Another model-authoring chat can
invoke this repository's absolute .venv Python from its own working directory, passing --avatar,
--source and --render-video. This is explicit offline file export, not automatic/live recording.
Every selected frame is inferred through an owned lockstep child and rendered on source time;
real-time arrival interpolation delay is zero. Output is MP4 (mp4v, silent), aggregate JSON and
optional --snapshot last-frame PNG. Default report is <video-stem>.report.json.

--start-seconds/--seconds select a source interval; omitted duration means all remaining frames.
--render-size defaults960x720; --clean-output removes review HUD/head inset. Existing files and
recording/model/profile inputs are protected. Encoded frames are reopened/count-checked before
exclusive staged-file publication; failed/changed-input/interrupted exports clean their temp files.
Existing headless smoke checks still default to10wall-clock seconds. PowerShell launcher mirrors
the new flags; its .txt sharing copy matches.

Actual supplied recording + stable local copy of the evolving model/profile:2209frames encoded,
zero skips,73.439941s at640x480/30.079fps, worker exit0. Processing208.84s did not shorten the movie.
Full video:.local\cli-video-export\model-review-full.mp4; JSON/PNG share its stem. Nine frames
extracted from the encoded video were inspected. A91-frame short export ran from outside this
repo; the real launcher produced a4-frame clean/unmirrored export with final settings metadata.
Availability881full/1256partial/72not-found and1546face-present matches prior exhaustive counts.
This does not certify perfect rigging, artistic quality or sensor accuracy. No input audio,
raw images, landmark arrays, personal calibration or camera credentials were exported.

374full-suite/37focused cases and Ruff pass. A focused run hit the existing2s early-stop test
budget; retained its XML and obtained unchanged serial passes.33packaged runtime/resource files
match current source. Handbook83pages/181citations and HTML pass; CLI handoff pages inspected.
Guide:docs\16-cli-video-rendering.md. Receipt:docs\evidence\cli-video-export-validation.json.
CLI module hash0f985cd4e67ddb5dad861e4bab1e16aaa7521398cffa67cdeae0027fe6b64135;
export module9b4ed21e782f9804399b84d06176b506e4926223a0fbe5d99323a563339ded83.

CONCURRENT WORK: limb-frame twist and face-loss head handover were authored separately and
preserved, not claimed as CLI implementation. Both the limb and CLI workstreams acquired numeric
prefix26; use full filenames, do not silently renumber completed work. Repository-wide aggregate
refresh is currently blocked by27_HEAD_TRACKING_HANDOVER.todo lacking catalogue-required completion
headers. Its content and the previous aggregate were left intact; the checker was not bypassed.
The CLI feature/package/scoped evidence are complete. Shared catalogue housekeeping is separate.
No helper is intentionally left running, live camera resumed or publication requested.
Completed CLI export handoff persisted as ep_819.

## Previous completed milestones

STUDIO RESPONSIVENESS COMPLETE. TODO25 is DONE. Owner reported lag, especially when dragging
the timeline. Profiling showed long avatar/clean/debug callbacks on Tk. Cooperative scheduling
and then avatar-only offloading both missed the declared budget; retained their failed reports.
Final design gives GraphicsWorker exclusive renderer mutation/OpenGL ownership and also draws
numeric skeleton/face views there. Tk services controls, installs completed images and keeps raw
debug separate. Control changes are queued; status snapshots are immutable.

Independent UI expiry clears already displayed stale images even while a draw is pending.
Source/seek/presentation epochs reject late results. Queued exceptions, graphics timeout and
shutdown failures are explicit; renderer resources close on their owning thread. Capture/MediaPipe
remain in the owned child process. No raw pixels enter avatar rendering.
Static dominant-role membership now uses numeric lookup; head/foot masks are cached read-only.
Eight authored studio/clean before/after images match exactly, including missing/stale cases.

Queued Tk-event p95 paused/playing:127.23/131.85ms before,18.25/20.74ms completed,
14.89/18.48ms repeat. Each phase delivered80positions and committed one seek. Both completed runs
meet50ms p95/150ms max input and50ms p95 heartbeat budgets with supplied GLB/recording, clean output
and both numeric debug views. These are software queue measurements, not physical input/sensor
latency, universal FPS or tracking accuracy. Source recording/model/profile unchanged.

312tests/no skips and Ruff pass. Native19Studio/9model/10motion/9debug groups and7generated/
8supplied timeline groups pass. One concurrent-book suite hit the existing2s early-stop test budget;
isolated and serial312-case reruns passed unchanged. Production safety thresholds were not weakened.
Book82pages/179citations and offline HTML checked; supplied-model UI and changed print pages inspected.
Readback verifies88source/resource hashes and32packaged runtime/resource files.
Current receipt:docs\evidence\studio-responsiveness-validation.json; prior aggregate:
docs\evidence\before-ui-responsiveness-validation.json. Private reports:.local\ui-responsiveness.
No implementation, testing, documentation or package work remains. Restart an older app instance
to load the responsive UI. No helper is intentionally left running, live camera resumed or publication.
Completed responsiveness handoff persisted as ep_816.

## Earlier completed milestones

REPLAY TIMELINE COMPLETE. TODO24 is DONE. The bottom Studio-only bar provides play/pause,
elapsed/duration and click/drag seeking on release. Focused slider keys: Left/Right one second,
Home/End boundaries. It is hidden for live/demo input and absent from clean renderer buffers.
File capture owns all decoder operations; coalesced IPC and seek generations reject old samples.
Seeks recreate the native tracker and clear rig/scale/filter history while preserving completed
session-only facial calibration/gains. Unfinished collection cancels. Paused numeric samples stay
explicitly labelled; original timestamps remain unchanged and raw preview still expires at600ms.
EOF releases the worker; a later seek restarts the same file at the requested position.

288full-suite tests/no skips and Ruff check/format pass. Native timeline groups7generated/8with
the supplied recording (overlapping), plus19Studio/9model/10motion/9debug groups pass.
The supplied MP4/GLB/profile remained unchanged. Requested18/30/18seconds produced
17.9861588/29.9880133/17.9861588seconds in the same worker;41inferred frames, exit0/unforced.
Generated frame markers prove decoder position; watchdog/EOF races and stale generations are
covered. Native1020x720layout and pixel-exact clean-output isolation pass. Screenshots inspected.
Timing uses frame index/reported FPS, not exact VFR timestamps or audio playback.

Initial native Pause readiness and UI-coupled authored-input fixtures failed. Helpers now await
enabled controls and produce authored samples independently of Tk pumping, with bounded cleanup.
No calibration, freshness or watchdog thresholds were weakened. Existing performance/native-DLL
and SDK telemetry limitations remain; this feature does not qualify motion accuracy or smoothness.
Guides, journal, TODO24 and82page/177citation handbook are current. Changed PDF pages56/62 and
offline HTML inspected/checked. Readback verifies84source/resource hashes and31packaged runtime files.
Current evidence:docs\evidence\replay-timeline-validation.json and prototype-validation.json.
Prior aggregate:docs\evidence\before-replay-timeline-validation.json. Private reports:
.local\replay-timeline. Generated temporary recordings were removed; no helper is intentionally left.
No implementation, validation, documentation or packaging work remains. Restart an older app instance
and use Test from video to see the controls. Await new direction; no live camera or publication.
Completed timeline handoff persisted as ep_814.

## Older completed milestones

COLLAPSIBLE STUDIO COMPLETE. TODO23 is DONE. All seven numbered right-panel sections use
CollapsibleSection and toggle independently. Input starts open, all others folded. Expand all
and Collapse all stay above the scroll area; collapsing all resets scrolling to the top.
Headers support mouse, Space/Enter and Tab navigation; folding a focused child returns focus
to its header. Bodies are hidden, not recreated, preserving widget identity, control values,
calibration, current model and running replay. Separate debug windows do not close when folded.

39focused tests across three modules,19native studio groups and9model groups passed.
Measured panel heights:2088pxall expanded,780pxdefault,273pxall folded. The folded layout fits
the1020x720minimum window. Inspected default/fully folded/native model screenshots and refreshed
the guides and82page/175citation handbook. Only scripted demo and blank synthetic replay used;
no real camera, private recording or user avatar file was opened for this UI change.
Current evidence:docs\evidence\collapsible-sections-validation.json. Previous scale receipt:
docs\evidence\before-collapsible-ui-validation.json. No tracking/renderer/scale algorithm changes.
Readback verified81source/resource hashes, all packaged runtime bytes and document/preview digests.
No code, UI, documentation or packaging work remains; use header toggles or Collapse all after
restarting an older instance. No helper intentionally remains running and nothing was published.
Compact-UI handoff persisted as ep_811.

TODO22 SCALE FIX COMPLETE: owner reported an enormous imported GLB versus the built-in on the same recording.
Reproduced with their explicit read-only model/profile: first scale1.460235 latched at2.128s
from14eligible joints/partial body. Later complete-pose estimates were2-4times smaller, and the
old formula also used inferred depth in screen-size measurement. Model dimensions are plausible.
Implemented projected2D span ratios plus per-observation log-scale smoothing, source/reset handling
and bounded missing-measurement retention. Relative bone lengths and source files are unchanged.
59focused cases passed again after PC restart. The full2209-frame comparison completed before the
shutdown;9model/10motion native groups passed. At18s ongoing/fresh-start scale is0.305634/0.303491;
sampled full-body fit differences stay within3.8%. Synthetic comparisons were inspected.
At23:40owner requested continuation after accidental PC shutdown. Confirmed files survived; a
fresh28snormal-runtime check processed201frames and ended cleanly/unforced with correct framing.
Two earlier normal-runtime attempts had failed with no frames and forced shutdown, one measuring
89smodel loading. Do not claim their slowdown's cause is known or silently discard those reports.
Docs/handbook and wheel are complete. The book remains82pages/175source citations; changed pages
were inspected, and all packaged runtime bytes match source. Preserved nine synthetic-only
before/after/default comparisons and the historical baseline. Sanitized evidence:
docs\evidence\imported-scale-validation.json. No implementation/runtime/book/package work remains.
Final readback verified80source/resource digests, all runtime wheel bytes,59focused test counts,
full2209-frame comparison and book/preview artifacts.
Completed scale-fix handoff persisted as ep_808.
No old validation command is assumed to remain running after shutdown.
Private artifacts:.local\scale-fix. Do not overwrite sibling Blender files or reopen the live feed.
The earlier temporary no-question window ended after2026-10-13T00:19:46+05:30.
Their running application must not be interrupted. This is an application placement fix, not
another instruction to manually rescale or re-export their Blender asset.
Final UI guidance: restart an older running TrickRoom instance and replay the same video/model;
automatic framing replaces the prior manual-recalibration workaround. Held/rest behavior and
different authored head/body proportions remain separate from this corrected zoom problem.

RECORDED VIDEO TEST VIEW COMPLETE. TODO21 is DONE. Under01/Input, Test from video opens a
file picker and drives the currently selected synthetic avatar from actual recording detections.
Replay last video starts a fresh worker after EOF or completed Disconnect. The last file is
session-only, never hard-coded or saved in settings. Selecting a recording switches an imported
bind/clip preview to tracking mode; it preserves the avatar and presentation/privacy preferences.
Active sources are not interrupted. Studio, head detail, stage and clean output label VIDEO REPLAY
separately from scripted demo or live camera. Raw input stays separately opt-in and starts off.

53focused cases passed across four modules; this is not a new full-suite run.14native studio
groups and9model groups passed. A bounded native check of the supplied recording processed125
inferred frames at478x850, exercised built-in/GLB/clean/black diagnostic views and shut down
cleanly. Source unchanged; no raw/landmark exports, live camera or detector-accuracy claims.
Private evidence:.local\video-test-view. Public source-private receipt:
docs\evidence\recorded-video-view-validation.json. Earlier199-test core receipt is archived as
docs\evidence\core-motion-validation.json. Aggregate receipts now list exact tested modules.
Verified new native screenshots, recording-driven synthetic previews and updated handbook pages.
Book remains82pages/175citations with13668word tokens; wheel matches all runtime source files.
Current79source/resource digests and preview/book hashes read back. No code, document, packaging
or validation work remains for this request; no helper is intentionally left running.
No commit, push, publication or persisted private source path. Live-camera testing stays paused.
Use the new picker and select the recording; restart an existing app instance to load the buttons.
Recorded-test-view handoff persisted as ep_802, with source, wheel and document readback complete.

FIRST CORE MOTION UPGRADE COMPLETE. Owner authorized implementation at14:06; TODO20 is DONE.
Implemented owned spawned camera/model inference with bounded snapshot IPC, Windows job ownership,
native-exit/watchdog errors and explicit forced cleanup. Studio no longer imports MediaPipe for
face-debug connections; licensed static topology is packaged instead. SDK telemetry is unchanged.
Imported GLBs now support separately filtered world directions, image/legacy comparison,
rest-aware bounded two-bone posing, arrival-adjusted interpolation and explicit
TRACKED/HELD/RETURNING/REST/REACQUIRING/UNAVAILABLE states. Relaxed loss is opt-in; whole-source
staleness600ms and total detection loss still clear geometry. Raw diagnostics remain observations.
Session-local face response adds neutral/range capture, per-channel gain and independent immediate
blink endpoints. No personal calibration, raw frames or landmark arrays are persisted.

199tests/no skips; twelve native studio/nine model/nine debug/ten new motion groups passed.
Final isolated recording:2209decoded/1851inferred/358skipped, EOF/exit0 and no forced child shutdown.
Every-frame dual-mode comparison:2209/2209, exact prior raw detection counts, bone-length error
1.97e-8maximum,2047intervals with intermediate poses. Enhanced rendering costs more:
16.13/21.56msmean/p95 versus12.16/16.16mslegacy in this diagnostic. No sensing-accuracy claim.
Existing Blender parity repeated against saved source samples:2.2469e-7wave/5.8990e-8face.
Synthetic comparison/native images and changed book pages inspected. New guide:
docs\15-core-motion-upgrade.md. Handbook refreshed to82pages/35chapters/175source citations,
including corrected pagination and green technical figures. Wheel rebuilt with topology/license.
Readback verified78source/resource files and current document/preview digests.

Important limits: GLB rig motion does not retrofit the built-in procedural character. The latter
keeps the reference art and supports process isolation/face response only. Initial close-up scale
can require Recalibrate once fully framed. Opt-in REST means authored rest pose (T-pose in the
technical fixture), not polished idle animation. Optional OpenSeeFace, VMC, spring/secondary
simulation and final reference-art Blender creation are not implemented in this core milestone.
No live camera was reopened; the prior live-testing pause stays in effect.
Private evidence:.local\motion-upgrade. Before snapshot:.local\motion-upgrade\before-source.zip.
Previous public receipt:docs\evidence\green-theme-validation.json. Current sanitized motion receipt:
docs\evidence\motion-upgrade-validation.json. No commit, push, publication or system-network change.
No implementation, validation, document or packaging work remains for this first core milestone.
Final core handoff persisted as ep_792. All runtime files in the rebuilt wheel match the source;
launcher sharing copies and78source/resource digests read back successfully.

PRECEDING VSEEFACE RESEARCH COMPLETE. Deliverable: docs\14-vseeface-research.md, with35source-reference
labels, two rendered/validated diagrams and a prioritized comparison against actual local code.
The following research paragraphs are the pre-implementation snapshot; the completed core upgrade
above supersedes their proposed/not-yet-used statements.
Read the official site/manual, full release history, English interface strings, pinned OpenSeeFace
tracking/animation/process code, SDK configuration, VMC spec, public Leap controller and RootMotion's
VRIK design article. Not the entire proprietary VSeeFace implementation or a binary-equivalence audit.

Key distinction: VSeeFace native webcam input tracks faces; hands normally use Leap Motion.
Full-body data may come from external VMC senders. Limited-target IK, calibration, interpolation,
loss transitions, facial composition and secondary motion account for much of the apparent polish.
Do not repeat "perfect full-body webcam tracking" as verified. Release history also supersedes
overbroad52shape claims: later iFacialMocap reception accepts subsets/translated controls;
full52control fidelity and basic compatibility are different.

Important local finding: Tracker records world_joints, but the current GLB retargeter aims bones
from normalized image-space points. World-space target evaluation is proposed, not implemented.
Imported rigs already preserve local bone lengths and rest-aware eye posing. Built-in procedural
parts instead use current landmark distances and disappear per eligibility. Avoid reimplementing
completed skinning or assuming the first video qualified the GLB path; it used the built-in avatar.

Recommended future work: isolated native inference; evaluate world-space rig directions;
timestamped display interpolation and explicitly labelled measured/held/rest/unavailable states;
per-channel facial calibration; constrained limb/twist control; later face-backend A/B and narrow
VMC support. Keep raw skeleton diagnostic truth and600ms source staleness. No new fallback behavior,
retargeting, models, dependency installs, runtime tests, camera use, private-video reprocessing or
firewall/proxy changes occurred. TODO19 is DONE; all recommendations remain proposals.
Source/tooling hash readback confirmed66files unchanged. Research receipt/cache is private under
.local\research\vseeface. Wait for the owner's next concrete implementation or experiment request.
Research handoff persisted as ep_791. Original research-milestone document SHA256 before the later
implementation-status link was added:
5105b639d59a451e8f217738cee8e6a5966d64f14b298b2c30f221216a1fce62.

FIRST RECORDED-VIDEO TEST COMPLETE. The owner supplied a recording and authorized a first test,
not application fixes. Normal unchanged playback reached EOF:2209decoded/2191inferred/18skipped,
exit0 and clean shutdown. A private synchronous diagnostic processed all2209frames and rendered
the avatar plus black skeleton/face views on every frame without exceptions.
Pose-present96.74%; full required skeleton39.88%; partial56.86%; face69.99%. Both blink channels,
jaw, smile and head-angle signals activated. No jump exceeded the12%-diagonal heuristic.
These are availability/activation results, not independently annotated gesture accuracy.
Face gaps around23.4-25.5s/41.1-43.2s and partial-body spans7.6-13.5s/57.0-69.4s need ground-truth
comparison. Nine synthetic samples were inspected; raw source frames were not manually compared.
Source remained unchanged; no raw frames, audio or landmark arrays were saved. Private reports,
assessment, diagnostic harness and synthetic contact sheet: .local\video-checks\20261012-first.

SDK DISCLOSURE: native MediaPipe emitted Clearcut usage-telemetry warnings. The upstream
collaborator in google-ai-edge/mediapipe#6291 confirms intentional telemetry/no official opt-out
and states inputs are never sent. This is upstream assurance, not an independent packet audit.
Do not claim the packaged runtime is network-silent, or suppress logs as a privacy fix.
TODO18 records an unstarted policy/remediation decision. No SDK/network settings were changed.

No application code was changed or startup fix made. Earlier integrated live/headless startup
crashes (WINHTTP.dll/c0000409 and diagnosticc000070a) did not recur on this video; root cause is
still unresolved. The interrupted earlier sequential-startup probe has no accepted result.
The previous live-only receipt remains .local\live-camera-checks\20261012-031803-tracking-only.json.
Live-camera testing remains paused: do not reconnect to the old endpoint. First offline test
is complete; wait for the next requested action rather than automatically applying fixes.
The previous pause handoff was ep_789. TODO07 remains IN_PROGRESS for broader qualification.
First-test handoff persisted as ep_790. Readback confirmed all2209frames, clean EOF/shutdown,
no raw/landmark exports and unchanged application/tooling hashes.

GREEN ROOM THEME COMPLETE: the latest reference is now reflected by near-black green panels,
thin vivid green grids/borders and no calibration crosses. Character geometry, room perspective,
decorative shadows, camera/tracking and private-debug behavior are unchanged. TODO17 is DONE.
169tests/no skips, twelve native studio groups and nine imported-model groups passed.
Landscape, portrait, empty, clean output and both native avatar paths were visually inspected.
Updated room/main previews, GIF, native screenshots and82page/175citation handbook.
An initial desktop-rectangle capture showed a lock screen, not the application, and was discarded.
Shared UI evidence now targets the application's HWND, rejects zero handles and skips unavailable
desktops explicitly. Eight regressions cover the helper; later actual app captures were inspected.
No owner camera or new user visual approval is claimed. Warm full-render median/p95 is
10.11/10.95ms, not physical camera latency. Earlier fixture/stream results remain historical.
The previous debug receipt is archived as docs\evidence\debug-before-green-theme-validation.json.
No implementation, validation, document or preview work remains for the requested room theme.
An already-running source process must restart to load the new cached palette; do not automatically
stop a user's camera session or start a source. No commit/push/publication was requested.
Theme handoff persisted as ep_788. Readback verified all66source-file hashes,26visual files,
PDF/HTML/manuscript hashes,169test counts and the preserved previous debug receipt.

PREVIOUS FOLLOW-UP COMPLETE: owner explicitly requested opt-in raw input, black skeleton and
connected face-mesh debug windows, plus local camera-auth defaults. The raw path is isolated
from avatar/clean output and default off. Credential values are stored only in ignored DPAPI
storage and must never be copied into source, docs, logs or this context. Do not record values.
All three views are implemented in the Private Debug Windows UI section. They use unmirrored
input coordinates and actual camera/replay observations, not invented detections from demo.
One opt-in read-only raw copy is paired atomically with its observation and released on
disable/stop/staleness. Raw windows are ordinary visible windows, not capture-excluded.
Requested local defaults were encrypted, read back and verified through the actual masked UI
without printing/capturing their values or opening a camera. No secrets were added to source.
159tests/no skips and nine native debug lifecycle groups passed; actual public-fixture
MediaPipe data rendered33pose points/478face points/1322unique mesh edges on black.
Docs\13-debug-views.md, TODO16, journals and the82page handbook were updated.
No implementation/validation/documentation work remains for this request.
Final debug/auth handoff persisted as ep_787. Source/book hashes and ignored encrypted-config
location read back successfully; credential values were neither printed nor added to context.

Last repository-wide aggregate source digest (before CLI/concurrent rig work; refresh blocked):
be1e51cd49ab55701886bbe5cdc80625f5e1ec9369e832152e469afbbbf8d6c1 (uncommitted).
The current handbook hashes are in docs\book\edition-manifest.json; concurrent authoring can
regenerate that book. Its current83page/181citation files matched their manifest at readback.

The preceding requested work is COMPLETE locally: actual Blender-exported model support followed by
a detailed50-100page authoring/rigging handbook. No implementation, conformance, authoring or
document-layout work remains for this request. No commit/push/publication was requested.

The supported delivery is Profile1 self-contained GLB2, not direct.blend/FBX/VRM import or every
Blender feature. Runtime supports bounded asset validation, mapped humanoid names, linear blend
skinning/four influences, morph-before-skin facial controls, embedded base-color textures,
OPAQUE/MASK, supported samplers/unlit/diffuse materials, LINEAR/STEP clips, fixed-length live FK
retargeting, hand aim, morph/eye-bone gaze, scale calibration and missing-data visibility.
The UI/CLI can load models, view reports, select live/bind/clips, recalibrate and return to the
built-in reference character. Invalid imports retain the previous model. Controls remain responsive
under two-window rendering after an8ms minimum Tk event-loop yield correction.

## Deliverables and exact evidence

- PDF: docs\TrickRoom-Blender-Authoring-Handbook.pdf -83A5 pages,35chapters/workshops,
  14143word tokens and181resolved source citations after the CLI handoff update.
  No blank/out-of-bounds-text pages.
- HTML/source/manifest: docs\book\index.html, AUTHORING.md, AUTHORING-resolved.md,
  edition-manifest.json. Browser checked35headings/8embedded decoded figures with no external
  image dependencies or horizontal overflow; representative print/diagram/table/code pages inspected.
- Quick start: docs\12-blender-models.md.
- Original technical fixtures: examples\blender\TrickRoom-Conformance and TrickRoom-EyeBones
  (.blend/.glb/.trickroom.json), plus conformance-build.json with hashes.
- Authoring utilities: tools\blender\preflight.py, export_character.py,
  create_conformance_rig.py and sample_conformance.py.
- Numerical/runtime check: tools\verify_blender_models.py. Actual Blender4.5.14 evaluated
  vertices match runtime wave/face samples to2.2469e-7 /5.8990e-8 maximum scene-unit error.
  Effective eye-bone mode also validated; not merely unused bone names.
-148tests/no skips; original12native groups plus9model-import UI groups passed. Source
  preflight/export reproduced the GLB hash without resaving the source.blend.
- Final imported-model loopback:57received/48inferred,48body+face,7skipped plus pending work;
  mean rendering9.05ms/inference36.55ms, postdecodeage63.06/66.44msmean/p95. Startup included.
  This is not owner-camera, real-motion footage or physical camera-to-display latency evidence.
- Prior Blender-only aggregate source digest (current theme revision is above):
  65ec292e4cbad1f4e44f1b8b7ce6ed5212c4df45d3006b7144c150fea4d5e451.
- Current aggregate receipt: docs\evidence\prototype-validation.json.
- All six actual fixture files and PDF/HTML/manuscript hashes were read back against their manifests.
- Blender handoff persisted as zmem ep_786; that milestone's source hashes matched its sealed receipt.

## Launch and import

Default built-in demo: .\Start-TrickRoom.ps1 -Demo
Imported technical demo:
.\Start-TrickRoom.ps1 -Demo -Avatar examples\blender\TrickRoom-Conformance.glb
CLI validation:
.\.venv\Scripts\python.exe -m trickroom --validate-avatar examples\blender\TrickRoom-Conformance.glb

Python3.12 .venv and runtime dependencies are installed. Blender4.5.14 was invoked read-only as
an executable from the SongsWorkspace tooling location; all new output belongs to TrickRoom.
Documentation extras and local Mermaid/Edge tooling are installed; see docs\book\README.md.
No helper is intentionally left running and no live camera was accessed for the core upgrade. Re-verify any
user-started process rather than assuming one is open or closed.

## Preserved earlier milestones

- M1 capture/face/body prototype, original book/history review and IP Webcam ingestion lineage.
- Reference avatar follows both owner-supplied sheets: dark spiky hair, beige headphones,
  warm angular face, charcoal hoodie, olive cargo pants and cream/taupe sneakers.
  This is near-final art direction; the conformance rig is not a substitute for that art.
- Perspective lab: five projected surfaces and decorative floor-clipped shoe shadows.
  The latest theme replaces the earlier pale grid/crosses with green lines and no cross markers.
  It is not physical room reconstruction/contact/collision.
- Prior M1/reference/room receipts remain under docs\evidence. Reference images are private
  under .local\references; originals unchanged. See docs\10-reference-avatar.md and11-perspective-lab.md.
- Older handoffs: ep_782 M1, ep_783 reference avatar, ep_784 perspective room.

## Remaining scope and open questions

- TODO01-06/08/11-17 are DONE. TODO07 first recorded-video pass is complete; broader qualification
  remains IN_PROGRESS and live testing is paused. Await the next requested review/fix.
  Never recover credentials from history, guess an address or reconnect automatically.
- TODO18 native SDK telemetry policy is NOT_STARTED. No system firewall/proxy or dependency
  changes are authorized merely by the completed first test.
- TODO19 research and TODO20 first core implementation are DONE. Optional backend/protocol/spring
  integrations remain subsequent work, not claims of this delivery. Detector accuracy is unapproved.
- TODO21 recorded-video test picker and replay control is DONE; no automatic looping or source
  persistence was added, and recorded input does not authorize resuming the old live endpoint.
- TODO22 imported scale is DONE. Old first-frame-scale limitations in previous milestones are
  historical and superseded by projected-span fitting with one smoothed update per observation.
- TODO23 collapsible studio sections is DONE. Fold states are session-only; folding is not a
  privacy toggle, disconnect, recalibration or permission to change the avatar.
- TODO24 recorded-video timeline is DONE. No transport, native-test, handbook or package work
  remains. Paused replay is explicit numeric inspection, not a change to live-source freshness.
- TODO25 Studio responsiveness is DONE. Renderer mutation/drawing belongs to GraphicsWorker,
  not Tk. No implicit follow-up optimization, live testing or publication is authorized.
- 26_CLI_VIDEO_EXPORT.todo is DONE. No CLI export implementation or artifact production remains.
  Use full filenames to distinguish the concurrent26_LIMB_FRAME_TWIST.todo; head-handover27
  is separately authored. Its catalogue-schema mismatch blocks aggregate documentation sealing.
- TODO09 is still NOT_STARTED for the actual final reference-art Blender character. Technical
  GLB/retarget support is now complete and must not be repeated as if still future.
- TODO10 interactive objects/physics is NOT_STARTED. Full finger capture, IK contacts,
  physical floor calibration and secondary simulation are not implemented claims.
- Real phone lighting/distance/occlusion, comfort, artistic approval and final character asset
  remain unverified. Do not infer approval from the user stepping away or from passing tests.
- The owner asked to proceed without questions during this work. Wait for the next concrete
  direction rather than automatically authoring the final avatar or publishing anything.

## Environment and continuity reminders

Only this base's .agent-context may be changed. Sibling sources/stores are reference-only.
Preserve the uncommitted tree and declared profile/handbook contract. No camera credentials,
raw media, biometric records or personal details belong in durable context.
Root JOURNAL.md and TODO\00_INDEX.todo are the implementation history and workstream catalogue.
