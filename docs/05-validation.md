# 05 - Validation and troubleshooting

## CLI reference-video export

The new explicit `--render-video` mode processes a selected recording frame by frame, through
owned native inference, instead of dropping frames to maintain real-time preview speed.
It writes a synthetic MP4 and aggregate report, plus an optional final-frame PNG. Source-relative
clocking is explicit; the output is not a capture-latency or perfect-rigging measurement.

The complete supplied reference was exported against a stable local copy of the current supplied
GLB/profile: **2,209 decoded/inferred/rendered/encoded frames**, zero skipped, **73.439941 seconds**
at encoded 30.079 FPS, 640x480, worker exit 0. All encoded frames were reopened/count-checked.
Export took208.84seconds on this run; slower processing did not shorten the recording.
Availability was881full/1256partial/72not-found body frames and1546face-present frames, matching
the prior exhaustive reference counts. These remain availability, not annotated accuracy.

A separate91-frame/3.025-second export was launched from outside this repository using its absolute
Python executable. The actual PowerShell launcher also produced a four-frame clean/unmirrored clip
and its default companion report. A PNG and nine-frame sheet extracted from the encoded synthetic
video were inspected; no raw reference images or audio were exported.

**374 full-suite tests** and37focused cases pass, plus Ruff. Coverage includes real MP4 decoding,
exact selected-frame ordering, worker response bounds, invalid timing/dimensions, output/input
collisions, changed inputs, cancellation, rollback and cleanup. One focused run exceeded the known
existing two-second early-stop test budget; its XML is retained and unchanged serial reruns passed.

Concurrent retarget/twist-test work was preserved and is included in the tested working tree, not
claimed as part of CLI export. The full video uses a stable local model/profile snapshot, avoiding
concurrent external artwork changes. Native SDK telemetry warnings still occurred; policy is unchanged.
The handbook is now83pages with181resolved source citations and a passing offline HTML check.

Usage and cross-chat handoff: [CLI model review](16-cli-video-rendering.md). Scoped evidence:
`docs\evidence\cli-video-export-validation.json`; actual videos/reports/previews:
`.local\cli-video-export`. Previous aggregate: `docs\evidence\before-cli-video-export-validation.json`.
The scoped export receipt and package readback are complete. A repository-wide aggregate refresh
is blocked by an independently written head-handover TODO missing the required completion section
headers; the previous aggregate remains intact. Concurrent limb/CLI entries share numeric prefix26,
so use full TODO filenames until that catalogue housekeeping is coordinated.

## Studio responsiveness revision

The expensive avatar/clean/debug redraws previously ran together on Tk's UI thread. The first
cooperative scheduling optimization was not sufficient; avatar-only background drawing also
missed the latency budget while numeric diagnostics were open. Avatar and numeric-debug drawing
now share one graphics owner, while Tk services controls and installs completed images.
Static anatomical masks are cached without changing visibility or output pixels.

The native check used the explicitly supplied recording/GLB with clean output and both black
diagnostic windows open. It queued 80 timestamped Tk drag positions per phase. These are software
event-queue measurements, **not physical pointer, camera or sensor-to-display latency**.

| p95 queued-event delay | Before | Completed | Repeat |
|---|---:|---:|---:|
| Paused recording | 127.23 ms | 18.25 ms | 14.89 ms |
| Playing recording | 131.85 ms | 20.74 ms | 18.48 ms |

Both completed runs meet the declared 50 ms p95/150 ms maximum input budget and 50 ms p95
heartbeat-lateness budget. Every gesture still committed exactly one seek. This demonstrates
local interaction improvement, not a guaranteed rendering FPS, tracking accuracy or performance
on every machine. Slow or superseded graphics results cannot restore stale/old-source displays.

**312 tests pass with no skips**, plus Ruff and native Studio/model/motion/debug groups
19/9/10/9. Generated and supplied timeline checks pass, including exact clean-output isolation.
Eight deterministic before/after images match pixel-for-pixel across full, cropped, missing-face
and stale cases. The recording/model/profile are unchanged; raw input remained off for their checks.

A full-suite run concurrent with book rendering exceeded an existing two-second early-stop test
budget. Its report is retained; the isolated case and subsequent serial full suite passed without
changing runtime timeouts. Native helpers now await actual graphics completion rather than fixed
sleep/model-commit proxies. The handbook remains 82 pages with 179 resolved source citations.

Evidence: `docs\evidence\studio-responsiveness-validation.json`; private measurements and retained
failed attempts are under `.local\ui-responsiveness`. The previous aggregate is preserved as
`docs\evidence\before-ui-responsiveness-validation.json`.

## Recorded-video playback timeline

The bottom Studio bar provides play/pause, click/drag seeking, keyboard one-second/Home/End
movement and elapsed/duration. It is separate from the renderer and hidden for demo/live input.
Seek generations reset native and presentation history without reusing old observations.
Completed facial calibration survives; paused numeric samples are explicitly labelled.

**288 tests passed with no skips**, plus Ruff check/format. Native checks passed seven generated
timeline groups and eight supplied-recording groups (the latter includes the generated cases),
19 general Studio groups, nine imported-model groups, ten motion-control groups and nine
private-debug groups. Checks include an active-worker watchdog during paused seek, decoder
frame markers, stale in-flight rejection, EOF races/restart, pause/shutdown, raw expiry and
pixel-exact control-free clean output. Timeline layout fits the minimum 1020x720 window.

The explicitly supplied recording and GLB were exercised without changing their bytes or the
profile. The bounded run inferred 41 frames. Requested positions 18, 30 and 18 seconds produced
media times 17.9861588, 29.9880133 and 17.9861588 seconds in the same worker; shutdown exited 0
without forced termination. This is transport/presentation evidence, not another exhaustive
movement test or an accuracy/smoothness qualification. No live camera was opened; raw preview
stayed off for the supplied recording. Native synthetic screenshots were inspected.

The first timeline probe failed to acknowledge Pause; its harness now waits for the enabled UI
control, not just a worker observation. Existing motion/debug probes also exposed UI-coupled
authored-input production: calibration missed its sample minimum and a raw preview expired.
Those producers now run independently with bounded cleanup, like the application's separate
input execution. No calibration sample minimum, raw expiry or watchdog threshold was relaxed.

The handbook remains **82 pages**, now with **177 resolved source citations**, no blank/overflow
pages and a passing offline HTML check. Timing remains frame-index/reported-FPS based, not exact
VFR timestamp handling. Earlier native startup/performance and SDK telemetry limitations remain.

Current evidence: `docs\evidence\replay-timeline-validation.json`, with private native reports in
`.local\replay-timeline`. Previous aggregate evidence is preserved in
`docs\evidence\before-replay-timeline-validation.json`.

## Collapsible-section UI revision

All seven numbered control sections now fold independently without rebuilding their widgets.
Input starts open; the others start folded. Expand all/Collapse all stay above the scroll area.
The native layout measured2088pixels with everything open,780with the initial selection, and
273with everything folded. All folded headers fit the minimum1020x720window.

**39 focused cases**,19native studio groups and9model groups passed. Coverage includes
Space/Enter activation, Tab traversal past hidden controls, returning focus to a folded header,
scroll bounds, preserving settings/widget identity and keeping active replay/debug windows intact.
Only authored demo motion and a generated blank replay were used; no live camera or private
recording was opened. Previous tracking/scale measurements are carried forward, not rerun.

Current UI evidence: `docs\evidence\collapsible-sections-validation.json`.
The previous scale milestone is preserved in `docs\evidence\before-collapsible-ui-validation.json`.

## Imported-avatar scale correction

The same-recording mismatch was reproduced with the supplied GLB. Its initial scale was
latched at **1.460235**, at about **2.128 seconds**, with only 14 eligible joints. Later
full-body observations could not update it. The previous estimator also counted inferred
depth in a screen-size ratio. The built-in avatar did not share that scale latch, explaining
the large difference despite an identical input video.

Scale now follows the median of at least three usable image/posed-rig projected spans, with
one log-space smoothing update per observation. Near end-on and tiny spans are excluded;
source changes and lost evidence reset or expire the estimate. The model's bone proportions
and input files are not modified.

The every-frame comparison completed **2,209 frames**. At about 18 seconds, corrected scale
was **0.305634**, compared with **0.303491** when starting fresh at the same pose; at the
four sampled full-body checkpoints, ongoing and fresh-start fits differed by at most **3.8%**.
Across full-body frames after 14 seconds, corrected scale was a median **22.6%** of the old
locked size. These are placement measurements, not detector-accuracy improvements.

**59 focused tests** passed; the nine imported-model and ten motion-control native groups also
passed. After the reported PC shutdown, a fresh 28-second runtime check processed 201 inferred
frames, returned fresh observations and shut down with exit 0 and no forced termination.
That run skipped many capture frames and rendered about 8 frames/second on average; it is
framing/cleanup evidence, not a smoothness or performance qualification.

Two earlier integrated attempts failed to acquire frames and required worker termination;
one measured about 89 seconds loading the model before the timed playback window expired.
Those failed reports remain private alongside the successful run. The cause of that slowdown
was not established and is not claimed to be fixed by the scale change.

Original GLB/profile/video remained unchanged. Private before/after/default-view comparisons
are in `.local\scale-fix`; sanitized evidence is in
`docs\evidence\imported-scale-validation.json`. The prior aggregate receipt is preserved as
`docs\evidence\before-scale-fix-validation.json`.

## Recorded-video test-view revision

The studio now has explicit **Test from video...** and **Replay last video** actions. A
53-case focused pass covers source selection/cancellation, file-only validation, active-worker
protection, imported-model preservation, replay labels, rendering and CLI/runtime behavior.
This was a targeted pass, not a new full-suite count. Fourteen native studio groups and nine
model-lifecycle groups passed.

A bounded native check selected the supplied recording through the new action, inferred125frames
at478x850, exercised built-in and GLB stages, clean output and both black debug views, then
disconnected cleanly. Raw preview remained off and the original file was unchanged.
It was not another exhaustive motion/accuracy assessment. Private synthetic previews and the
source-private report are under `.local\video-test-view`; aggregate evidence is
`docs\evidence\recorded-video-view-validation.json`. The previous199-case core-motion receipt
is preserved as `docs\evidence\core-motion-validation.json`.

## Core motion implementation revision

The new process/rig/face modules passed **199 tests with no skips** and the existing native
studio, model and private-debug checks. Ten additional native motion-control groups exercise
world/image/legacy switching, explicit relaxed loss states, stale clearing, neutral/range
calibration, unchanged raw coefficients and SDK-free debug rendering.

The final isolated-worker recording run decoded2209frames, inferred1851 and skipped358,
reached EOF and exited cleanly without forced termination. Mean inference was35.91ms.
This is a heavier imported-rig run, not an improvement over the earlier built-in throughput
measurement; load and frame-skipping differ. No live camera was reopened.

The every-frame comparison processed all2209frames through both the legacy and enhanced
technical GLB presentation paths. Raw availability remained exactly72not-found,
1256partial,881full-body and1546face frames, matching the first exhaustive pass.
Authored bone-length error stayed below2e-8scene units. The enhanced pose changed between
detection frames in2047sampled intervals, and held/rest regions remained distinct from detections.
Legacy/enhanced mean render times were12.16/16.13ms; p95 was16.16/21.56ms in this diagnostic.
Those timings exclude the separate extra mid-frame assertion sample and are not live latency.

At that milestone, synthetic samples exposed a placement limit: scale calibrated during the
clip's initial close-up could leave the later body too large. Recalibrating while fully framed
was the earlier workaround.
The optional rest pose is the model's authored rest pose, which is a T-pose for this fixture.
Neither issue is silently represented as fully polished or artistically approved behavior.
The later workstream22 framing fix supersedes that first-frame scale limitation; the authored
rest-pose observation remains applicable.

Source remained unchanged. Reports and comparison images are private under
`.local\motion-upgrade`; only sanitized aggregate evidence is copied to
`docs\evidence\motion-upgrade-validation.json`. The earlier
`docs\evidence\green-theme-validation.json` preserves the preceding implementation milestone.
No new sensing-accuracy or native-DLL root-cause claim is made.
The maintained authoring handbook now has82A5pages,35chapters and175resolved source citations,
with no blank/out-of-bounds text and a self-contained offline HTML edition.

## First supplied-recording test

The first73.44second,478x850recording test is complete. Unmodified playback reached EOF,
decoded2209frames and inferred2191, skipping18(0.81%). It exited successfully with clean
shutdown. The earlier native startup crashes did not recur in this run, but remain unexplained.

A separate synchronous diagnostic then processed all2209frames without playback skipping.
The avatar, black skeleton and black face views rendered for every frame without exceptions.
Pose was present in2137frames(96.74%), all required body joints in881(39.88%), a partial body
in1256(56.86%), and a face in1546(69.99%). Both blink channels, jaw, smile and head-angle
controls activated. These are detector results, not independently annotated motion accuracy.

Face gaps included23.439-25.467s and41.092-43.153s. Partial-body spans included7.613-13.465s
and56.951-69.351s. They must be compared with intentional framing/occlusion before labelling
them algorithm failures. No joint jump exceeded the diagnostic12%-of-diagonal threshold;
smaller jitter and incorrect but smooth poses are not ruled out.

The source remained unchanged. Only aggregate reports and a nine-frame synthetic contact sheet
were saved privately in `.local\video-checks\20261012-first`; no raw camera frames or landmark
arrays were saved. No application code was changed. Live-camera testing remains paused.

## Native SDK telemetry caveat

Both recorded-video passes emitted `portable_clearcut_uploader.cc` warnings. A MediaPipe
maintainer confirms that prebuilt SDK telemetry is intentional and has no official opt-out;
they state that input data is never sent. See
[google-ai-edge/mediapipe#6291](https://github.com/google-ai-edge/mediapipe/issues/6291#issuecomment-4896121772).
That input-data statement is upstream documentation, not a packet-content audit performed here.
Local inference therefore must not be described as network-silent. Suppressing logs is not
disabling telemetry. Workstream18 records this open policy decision; no system settings or SDK
were changed. Telemetry has not been established as the cause of the earlier native crash.

## Green-wireframe implementation revision

The palette/marking update passed **169 tests with no skips**, twelve native studio groups and
nine imported-model groups. The room retains its projection, reference character and decorative
shadow behavior; near-black green panels and thin green grids replace the slate theme and crosses.
The two room-theme regressions verify the palette and the absence of calibration crosses.

An initial desktop-rectangle screenshot showed the lock screen rather than the application and
was discarded. UI verification now captures the test application's window handle, refuses a
zero handle and logs an explicit skip if the normal Windows desktop is unavailable. Eight new
tests cover those paths. Actual subsequent built-in/model UI captures were visually inspected
before updating the documentation; no configured private values appear in them.

The main/room previews, GIF, native screenshots and82page/175citation handbook are refreshed.
The warm gallery render measured10.11/10.95ms median/p95. This revision did not open the owner's
camera or repeat the earlier public-fixture/loopback motion checks; those results below are
historical. Current evidence is `docs\evidence\prototype-validation.json`; the preceding debug
receipt is preserved as `docs\evidence\debug-before-green-theme-validation.json`.

## Previous private-debug revision

The explicit debug-window/auth-default update passed **159 tests with no skips** and the
nine native debug-window lifecycle groups. The three views start off, remain separate from
clean output, close/reopen correctly, and clear raw retention on disable/stop/staleness.
Actual MediaPipe output from the existing public fixture rendered33pose points and478face
points with1322unique tessellation edges on black; no raw fixture image was saved by that check.

Requested local auth defaults were encrypted and verified with Windows user-bound DPAPI.
A real UI launch confirmed resolved defaults prefill the fields and the password is masked,
without printing or capturing values and without opening a camera. Values are absent from
source, documentation, context and reports. The ignored encrypted file is not a shipped default
for another user's clone.

The handbook was refreshed with the explicitly authorized raw-debug exception; it remains82pages,
35chapters and175resolved citations, with no blank/out-of-bounds text or HTML image/layout issues.
Source/data records remain explicit about synthetic/native/public-fixture evidence versus
actual owner-camera qualification.

## Previous Blender interoperability revision

The Profile1 imported-model pipeline passed **148 tests with no skips**, the original twelve
native studio groups and nine dedicated model-import UI groups. Actual Blender4.5.14 exports
were imported and compared numerically against Blender-evaluated geometry: maximum vertex
errors were2.2469e-7 for the wave and5.8990e-8 for the facial clip. The alternate eye-bone
fixture produced0.01051scene-units of eye-vertex motion under its gaze test.

A final isolated imported-model loopback completed48body/face inference frames from57received
frames during the bounded run, with7skipped sequence numbers and pending work at the sampling
boundary. Mean rendering was9.05ms and mean inference36.55ms; post-decode age averaged63.06ms
with66.44ms p95. The endpoint estimator reported30.62Hz. Startup is included; this is not
the owner's camera or physical exposure-to-display latency.

The authoring guide is **82 A5 pages**,35chapters/workshops and175resolved source citations.
PDF checks found no blank or out-of-bounds-text pages. The offline HTML decoded all8embedded
figures, exposed35chapter headings and had no external-image dependencies or horizontal overflow.
Representative print pages, diagrams, tables, code and browser layout were inspected.

A native clean-output check exposed redraw starvation when two windows exhausted the frame
budget and a1ms retry kept Tk busy. A diagnostic timeout located the active `_tick`/update
path. An8ms minimum event-loop yield fixed the repeated check; camera inference stays independent.
The dedicated UI checker now has a bounded traceback timeout rather than hanging indefinitely.

Current evidence: `docs\evidence\prototype-validation.json`, the handbook edition manifest,
`examples\blender\conformance-build.json` and the original technical fixtures.
Unsupported Blender/glTF features remain explicit in the guide; final-art approval, owner-camera
qualification, richer hand tracking, IK contacts and physics are not claimed.

## Previous perspective-lab revision

The enclosed lab passed **107 tests with no skips**, twelve native studio groups, all five
actual-model/public-fixture cases and same-session translation/loss/reacquisition.
Room-specific checks cover shared perspective convergence, foreshortening, floor projection,
immutable bounded caching, shadow clipping/overlap, eligible shoe geometry and exact mirroring.
The actual Tk room toggle and clean-output paths were exercised.

At 23:33 +05:30 on 2026-10-11, the completed room/character pipeline received 117 frames from
the 30 Hz loopback source and inferred 116, all 116 with body and face; one sequence was skipped.
Mean inference was **30.17 ms**, mean rendering **15.46 ms**, and mean/p95 post-decode observation
age **55.82/87.22 ms**. The instantaneous endpoint estimator reported 32.01 Hz; this is not a
claim that the source generated more than 30 images per second. All helpers shut down.

The separate warmed room-gallery render measured 11.03 ms median and 12.25 ms p95.
Character geometry remains 5,616 triangles, unchanged by the room. The backdrop itself is five
authored pinhole-projected surfaces and cached calibration markings, not inferred camera geometry.
Foot shadows are decorative cues, not measured ground contact.

Current source-linked receipts: `docs\evidence\prototype-validation.json`.
The preceding reference-character receipt is retained at
`docs\evidence\reference-avatar-validation.json`. No owner camera, real motion recording,
physical camera-to-display latency, owner art approval or interactive physics is claimed.

## Previous reference-avatar revision

The reference-driven clothing/head update passed **90 tests with no skips**, eleven native
studio groups, the five actual-model/public-fixture cases and same-session translation/loss/
reacquisition. The native checks include the new default-off diagnostics and real synthetic
replay/EOF handling. All of this is separate from owner-camera qualification.

At22:57+05:30 on2026-10-11, the updated30Hz loopback run received110frames and inferred108,
all108 with body and face; one sequence was skipped and one frame was still pending.
Mean inference was31.35ms, mean renderer time15.55ms, and mean/p95 post-decode observation
age51.93/82.02ms. Its endpoint rate estimator reported31.54Hz; this is not extra source frames
or a physical camera-latency measurement. All helpers/workers shut down.

The reference turnaround's separate warmed render sample measured9.64ms median and10.84ms p95.
The complete model has5,616triangles including coplanar material tiles, not an inferred copy of
the sheet's illustrated mesh. The OpenGL3.3 AMD Radeon780M context, depth ordering, bounded
framebuffer cache, resource cleanup and explicit graphics-failure path were exercised.

Reference-only source-linked receipts: `docs\evidence\reference-avatar-validation.json`.
The sections explicitly labelled original below and `docs\evidence\m1-prototype-validation.json`
preserve the earlier mannequin milestone; their timing/counts are historical, not the current revision.

## Evidence policy

Tests, real model execution, live camera observations and human visual approval are separate.
No camera endpoint was configured during initial implementation. Nothing in this chapter
claims full live-camera qualification, user approval, or physical camera-to-display latency.
The first supplied recording adds actual local-video execution evidence, not manual
frame-by-frame ground-truth accuracy or a solved native-startup issue.

The public fixture exercises both real models, not mocked detections. A deterministic translated
still can prove the plumbing follows changed pixels, but does not prove real articulation,
occlusion, motion blur or natural-expression accuracy.

## Commands

```powershell
# Local regression suite and style checks
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m ruff format --check src tests tools
.\.venv\Scripts\python.exe -m pip check

# Reference views and graphics/geometry evidence (authored poses)
.\.venv\Scripts\python.exe tools\render_avatar_gallery.py
.\.venv\Scripts\python.exe tools\render_room_gallery.py

# No camera: renderer, stats, explicit synthetic-only PNG
.\.venv\Scripts\python.exe -m trickroom --demo --headless --seconds 5 `
  --snapshot .local\demo.png --report .local\demo-report.json

# Real native Tk window, controls and bounded shutdown; no physical camera
.\.venv\Scripts\python.exe tools\check_studio.py

# Generated recording: actual playback controls and clean-output isolation
.\.venv\Scripts\python.exe tools\check_replay_timeline.py

# Actual Studio event-queue responsiveness; explicitly selected files, no physical camera
.\.venv\Scripts\python.exe tools\check_ui_responsiveness.py `
  --video "C:\your-folder\movement.mp4" --avatar "C:\your-folder\character.glb"

# Optional explicitly selected local inputs; no camera or raw-frame export
.\.venv\Scripts\python.exe tools\check_replay_timeline.py `
  --video "C:\your-folder\movement.mp4" --avatar "C:\your-folder\character.glb"

# Explicit public-fixture retrieval and real inference (not run by normal startup)
.\.venv\Scripts\python.exe tools\verify_tracking.py --download-fixture --output .local\fixtures

# Real MJPEG/capture/inference/rendering loop on loopback, not the phone
.\.venv\Scripts\python.exe tools\verify_stream.py
```

The public-fixture verifier accepts only its pinned image hashes. During development the
Pixabay CDN returned HTTP 403 to Python urllib even though the public tutorial image was
retrievable with PowerShell. The successful run used those already downloaded, checksum-matched
files with `--output .local\fixtures`; it did not silently substitute another image.
If retrieval is unavailable, report that limitation. The fixture script never downloads
an alternate image to make a failing test pass.

Normal unit tests have no network/model-download dependency. Native UI and actual inference
checks are explicit tools because they create windows or require external model/fixture files.

## Initial measured environment

Windows; Python 3.12.10; MediaPipe 0.10.35; OpenCV 5.0.0 (package 5.0.0.93);
NumPy 2.5.3; Pillow 12.3.0; Tk 8.6. MediaPipe reported the CPU XNNPACK delegate.
`requirements-lock.txt` records the complete verified package set.

The two model hashes are checked at startup; their versioned URLs and hashes live in
`src\trickroom\models.py`. A corrupt existing file is rejected, not replaced automatically.

## Original tracking milestone: actual-model fixture results

Recorded 2026-10-11 at 21:26 +05:30, 16 repeated input frames per case:

| Case | Visible pose points | Face frames | Warm mean / p95 inference | Meaning |
|---|---:|---:|---:|---|
| Full body, profile face | 33 | 0/16 | 25.96 / 27.65 ms | Body works; this profile face does not acquire |
| Seated body with visible expressive face | 33 | 16/16 | 25.20 / 27.99 ms | Both models and pose-guided face crop work |
| Cropped lower legs | 24 | 0/16 | 23.34 / 26.99 ms | Partial body; unavailable ankles omitted |
| Portrait crop | 33 | 0/16 | 22.08 / 23.93 ms | Aspect/crop path executes; visibility remains model-estimated |
| Blank frame | 0 | 0/16 | 16.38 / 17.45 ms | No hallucinated application fallback body/face |

The same-session test translated the front-facing fixture by 35 pixels, observed approximately
31.19 pixels of shoulder motion and 34.24 pixels of face-center motion, cleared on blank input,
and reacquired body plus face. Those are image-space test deltas, not body measurements.

Six crop sizes (64, 80, 96, 112, 144 and 180 pixels) also failed on the profile face.
That finding is retained instead of lowering confidence until the test reports success.

Timing is warm repeated-still inference on this machine, not total camera latency or a promise
of 30 tracking updates per second on every source. Current source may produce slightly different
timing after maintenance; dated receipts distinguish runs.

## Original tracking milestone: regressions and native checks

The first local suite reached 65 passing cases after correcting an assertion that expected
the wrong argparse exception class. **That milestone ended with70passing cases, no skips.**
Additional coverage includes wrist availability, control-character rejection, interrupt cleanup,
transient HTTP reconnect and old-frame invalidation.
The native studio passed ten groups with no callback exceptions:
window rendering, demo labelling, cropped-body status, presentation controls, clean output,
invalid-source rejection, disconnect, demo restart, actual-model synthetic replay/EOF controls,
and close. The replay check waits for real worker cleanup rather than relying on a fixed sleep.

The first actual positive inference exposed HxWx1 masks from this MediaPipe build.
The normalizer now explicitly accepts that singleton channel and retains a test for it.

`JOURNAL.md` records later/final counts and loopback evidence. Reports live under ignored
`.local` during a run; sanitized aggregate delivery evidence is retained under `docs\evidence`.
No original public fixture or owner camera media is committed with the source.

## Original tracking milestone: timed loopback result

On 2026-10-11 at 21:27 +05:30, a five-second run (including model startup) received 112 frames
from a 30 Hz loopback MJPEG server. Inference completed 111 frames, all with body and face,
with zero skipped sequence numbers and one frame still pending at the measurement boundary.
All server/capture/inference workers shut down.

- Mean inference: **27.34 ms**.
- Mean synthetic rendering: **7.18 ms**.
- Mean / p95 post-decode observation age: **45.62 / 67.12 ms**.
- Reported smoothed instantaneous inference rate at the endpoint: **31.51 Hz**.

The last rate is an estimator and can temporarily exceed the source rate during catch-up; it
does not mean the 30 Hz source produced more than 30 new images per second. This test used
translated public stills, not real human motion, and did not measure phone exposure/encoding/
network latency. The useful outcome is that the whole implemented transport/tracking/rendering
path operated at the supplied local stream cadence rather than merely rendering a demo.

## Troubleshooting

| Symptom | Check |
|---|---|
| Still says demo | Click Connect after entering the real endpoint; demo never accesses a camera |
| HTTP 401/403 | App credentials and server permissions; do not disable authentication |
| HTTP 404 | Use `/video`, not the app settings page |
| Timeouts | Phone server state, network/tethering route and exact address |
| Wrong orientation | Disconnect, change input rotation, reconnect |
| Motion reversed | Toggle output mirror; turn off a second mirror in the phone app |
| Body appears but face is grey | Face inference is unavailable; increase real face detail/lighting or face camera more directly |
| Legs vanish | Check framing, visibility and presence; the prototype does not guess missing legs |
| Silhouette imperfect | Segmentation is estimated; use skeleton overlay to separate mask versus pose problems |
| Old pose clears | Result crossed the 600 ms local post-decode freshness boundary |
| Slow tracking | Compare capture/inference/display rates; try smaller `--tracking-size` before changing models |
| Missing/corrupt model | Run the explicit model setup; remove a known corrupt model before retrying |
| OpenGL3.3 unavailable | Verify graphics drivers/context support; setup installs ModernGL, not a graphics driver |
| Driver stalls on exit | Native device calls depend on the driver; the shutdown error is not reported as successful cleanup |

## Live qualification still required

Use `TODO\07_LIVE_CAMERA_QUALIFICATION.todo`. Verify neutral stance, arm/leg movement,
walking across the frame, both winks, blinking, jaw/smile/brows, head turns, lower-leg crop,
temporary occlusion, leaving/reentering, phone disconnect/reconnect and source-to-display timing.
Use only the clean synthetic window for externally recorded output unless raw testing is
separately authorized. Feedback is evidence; do not pre-check this workstream.
