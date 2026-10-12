# CLI video rendering for model review

Use this when a model-authoring session needs a repeatable **GLB + reference recording -> synthetic
video** run, without opening Studio. It processes every selected source frame instead of sampling
a real-time preview. No camera is opened, and source pixels/audio are not included in the outputs.

## Run from any working directory

Use TrickRoom's existing isolated Python, not another project's environment. All input/output
paths below are examples; replace them with the actual absolute paths.

```powershell
$TrickRoom = 'C:\devdesk\homedesk\TrickRoom\.venv\Scripts\python.exe'

# Structural preflight: no camera and no motion inference
& $TrickRoom -m trickroom `
  --validate-avatar 'C:\models\Character.glb' `
  --report 'C:\reviews\character-v01-preflight.json'

# Entire reference recording, with a final-frame PNG for direct image inspection
& $TrickRoom -m trickroom `
  --avatar 'C:\models\Character.glb' `
  --source 'C:\references\movement.mp4' `
  --render-video 'C:\reviews\character-v01.mp4' `
  --report 'C:\reviews\character-v01.json' `
  --snapshot 'C:\reviews\character-v01-last.png' `
  --no-mirror
```

`--render-video` selects offline/headless operation; `--headless` is not additionally required.
The default mapping sidecar is `Character.trickroom.json` beside the GLB. Use `--avatar-profile`
for another mapping. Omitting `--avatar` renders the built-in reference character instead.

Existing export outputs are **never overwritten**. Use versioned/new names. The recording,
model and mapping must remain unchanged during the run; if another authoring process is editing
them, export a fixed revision/copy first. A change detected before completion rejects the outputs.

## Short iteration before a full render

```powershell
& $TrickRoom -m trickroom `
  --avatar 'C:\models\Character.glb' `
  --source 'C:\references\movement.mp4' `
  --render-video 'C:\reviews\character-v02-short.mp4' `
  --snapshot 'C:\reviews\character-v02-short-last.png' `
  --start-seconds 16 --seconds 3 --render-size 640x480 --no-mirror
```

This starts at the available frame at/before 16 seconds and processes the next three source
seconds, rounded up to whole frames. Without `--seconds`, export continues through the remaining
recording. Export duration refers to **source time**, not how long inference/rendering takes.
A slower computer does not shorten the video or skip reference frames.

The launcher also supports the same operation:

```powershell
& 'C:\devdesk\homedesk\TrickRoom\Start-TrickRoom.ps1' `
  -Source 'C:\references\movement.mp4' -Avatar 'C:\models\Character.glb' `
  -RenderVideo 'C:\reviews\character-v03.mp4' -StartSeconds 16 -Seconds 3 `
  -RenderSize '640x480' -NoMirror
```

Use absolute paths when calling the launcher from another base; it runs inside the TrickRoom root.
The Python command can also use paths relative to its caller's working directory.

## Options and artifacts

| Option | Meaning |
|---|---|
| `--render-video PATH.mp4` | Required opt-in video output; no Studio windows |
| `--source PATH` | Existing recording; URL/device sources are rejected in export mode |
| `--avatar PATH.glb` | Prepared imported model; optional mapping through `--avatar-profile` |
| `--start-seconds N` | Source start, default 0; rounded down to a valid frame |
| `--seconds N` | Selected source duration; omitted means all remaining frames |
| `--render-size WIDTHxHEIGHT` | Default 960x720; even dimensions, 320x240 through 4096x4096 |
| `--clean-output` | Remove review HUD/head inset; retain the truthful replay label |
| `--snapshot PATH.png` | Optional last rendered synthetic frame, before lossy video encoding |
| `--report PATH.json` | Aggregate evidence; default is `<video-stem>.report.json` |
| `--no-mirror` | Useful for anatomical left/right checks; does not change inference input |
| `--rotate left/right/180` | Rotate reference pixels before inference |
| `--rig-space image` | Compare image-based versus default world-based posing |
| `--no-rig-motion` | Compare the legacy strict rig path |
| `--no-rig-constraints` | Disable bounded limb constraints for comparison |
| `--relax-missing` | Explicitly allow labelled held/rest presentation; not new detections |

`--avatar-mode bind` or an authored clip is not accepted here: the video must be driven by its
reference detections. Existing `--headless --avatar-mode ... --snapshot ...` remains available
for bind/clip smoke checks. Existing headless checks without `--seconds` still run for 10 seconds.

Output uses the available OpenCV **MPEG-4 Part 2 (`mp4v`) encoder**, not an H.264 encoder claim.
It is silent. Use a desktop video player or OpenCV; browser codec support varies. Source timing
uses reported FPS/frame indices, not exact variable-frame-rate presentation timestamps.

## Model-authoring review loop

1. Validate the GLB/profile. Fix structural errors before judging movement.
2. Render a short interval containing the problematic pose, using a new versioned output name.
3. Inspect the MP4 and PNG: proportions, shoulders/forearms, twist, knees, feet, head orientation,
   facial controls, clothing intersections and viewport framing.
4. Read the JSON alongside the pictures. `tracking_availability` distinguishes full/partial/not-found
   body samples and face presence. Missing source evidence is not automatically a model defect.
5. Repeat with the same recording, interval, view size, mirror and motion flags after an asset edit.
   Compare model hashes to ensure the intended revision was loaded.
6. Run the whole recording once the short cases look acceptable, and review its difficult sections.

The report includes source/model hashes, selected/encoded frame counts, actual encoded FPS and
duration, model bindings/shapes/warnings, tracking availability and unmeasured presentation states.
`skipped_source_frames` must be zero; exit code 0 means the encoded video was reopened and every
expected frame decoded. The video, JSON and optional PNG are staged first and published without
clobbering existing files. Failed/interrupted exports remove their temporary output files.

The optional PNG is the last frame of the selected interval, not a raw-camera screenshot. To
inspect another moment, select a short interval around it or extract a frame from the synthetic
MP4. Keep source footage private; do not automatically publish it in a comparison report.

## Limits and evidence boundaries

Native inference stays in an owned spawned child with bounded request/response and shutdown.
Only numeric observations cross to rendering. Offline observations explicitly use source-relative
time for tracking filters and presentation; they are not live-capture latency measurements.
The real-time interpolation delay is zero for offline export, since every frame is available
and there is no arrival jitter to conceal. Missing joints/face remain unavailable by default.

Availability counts, valid bone bindings and a successful render **cannot certify perfect rigging,
shape, tracking or artistic quality**. A single camera can misestimate depth/twist/occlusion.
Model geometry/weights, tracker mistakes and presentation constraints must be judged separately.
`model_visual_approval` therefore remains false in automated reports.

Normal launch still does not record. No personal calibration, raw pixels, input audio or landmark
arrays are written by this command. MediaPipe's previously documented SDK telemetry caveat remains;
offline/local inference is not a network-silence guarantee.

Implementation: `cli.py::main`, `video_export.py::RecordingReader`,
`video_export.py::export_video`, `video_export.py::verify_video`.
