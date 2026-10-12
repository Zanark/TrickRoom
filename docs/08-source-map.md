# 08 - Source map

| Path | Responsibility |
|---|---|
| `src\trickroom\__main__.py` | Module entry point |
| `src\trickroom\cli.py` | Desktop/headless modes, explicit model setup and aggregate reports |
| `src\trickroom\video_export.py` | Lockstep owned inference, source-clock synthetic MP4 export and protected artifact publication |
| `src\trickroom\camera.py` | Safe source parsing, MJPEG/auth, latest-frame capture, rotation and decoder-owned replay transport |
| `src\trickroom\models.py` | Official versioned model URLs, hashes and atomic downloads |
| `src\trickroom\state.py` | Image-free immutable points, expressions, face and observation contracts |
| `src\trickroom\tracking.py` | Same-frame pose/face inference, head crop, normalization and contours |
| `src\trickroom\filters.py` | Time-aware One Euro motion filtering and reacquisition resets |
| `src\trickroom\runtime.py` | Owned inference, coalesced replay commands, seek generations, latest observations and status |
| `src\trickroom\worker_lifetime.py` | Windows job ownership for the isolated native tracking process |
| `src\trickroom\face_response.py` | Session-only neutral/range calibration and bounded facial response |
| `src\trickroom\face_topology.json` | Licensed static face connectivity; avoids native SDK imports in Studio |
| `src\trickroom\debug_views.py` | Isolated opt-in raw input and black skeleton/face diagnostics |
| `src\trickroom\credentials.py` | Windows-user-encrypted local defaults, never repository secrets |
| `src\trickroom\render.py` | Synthetic stage, character placement, optional diagnostics and HUD |
| `src\trickroom\graphics_worker.py` | Bounded single-owner rendering/control queue, status snapshots and OpenGL cleanup |
| `src\trickroom\avatar.py` | Reference-driven cached geometry, materials, expression parts and posing |
| `src\trickroom\raster.py` | OpenGL3.3 per-pixel depth, synthetic-alpha composition and resource lifecycle |
| `src\trickroom\room.py` | Pinhole-projected lab surfaces, bounded backdrop cache and decorative floor shadows |
| `src\trickroom\assets\profile.py` | Version1 humanoid names, shape controls, gaze mode and resource limits |
| `src\trickroom\assets\gltf.py` | Bounded GLB/accessor/node/skin/material/morph/clip validation and import |
| `src\trickroom\assets\animation.py` | Clip sampling, global transforms, morph-before-skin deformation |
| `src\trickroom\assets\retarget.py` | Fixed-length live FK, visibility, expressions/gaze and model mode state |
| `src\trickroom\assets\motion.py` | Bounded rig-pose interpolation and explicit loss/reacquisition states |
| `src\trickroom\assets\kinematics.py` | Rest-aware limb aiming and bounded two-bone solving |
| `src\trickroom\assets\presentation.py` | Imported model scale calibration, stage placement and head view |
| `src\trickroom\demo.py` | Explicitly synthetic authored motion and cropped-body demonstration |
| `src\trickroom\studio.py` | Collapsible native controls, Studio-only replay timeline, meters and clean window |
| `tests\` | Network-free unit and local-loopback regression tests |
| `tools\verify_tracking.py` | Explicit actual-model/public-fixture and reacquisition checks |
| `tools\verify_stream.py` | Real MJPEG/inference/render loop on local public-fixture transport |
| `tools\check_studio.py` | Bounded native Tk checks and own-window synthetic screenshot |
| `tools\check_replay_timeline.py` | Native pause/seek/EOF/layout checks with generated or explicitly supplied recorded input |
| `tools\check_ui_responsiveness.py` | Background-timestamped Tk drag events and heartbeat latency in actual Studio |
| `tools\ui_capture.py` | Application-HWND-only UI evidence, invalid-handle rejection and unavailable-desktop skips |
| `tools\render_gallery.py` | Original synthetic documentation images/GIF/hash manifest |
| `tools\render_avatar_gallery.py` | Authored character/body/head turnarounds and expression review |
| `tools\render_room_gallery.py` | Perspective lab views, camera/projection parameters and visual hashes |
| `tools\blender\` | Real Blender fixture creation, source preflight, export and numerical sampling |
| `tools\verify_blender_models.py` | Blender/runtime numerical comparison and model rendering evidence |
| `tools\check_model_studio.py` | Native asynchronous import, mode, failure-retention and cleanup checks |
| `tools\check_motion_studio.py` | Native motion, calibration, loss-state and diagnostic-isolation checks |
| `tools\verify_motion_upgrade.py` | Explicit local-video every-frame rig comparison with synthetic/aggregate-only outputs |
| `tools\build_blender_handbook.py` | PDF/HTML authoring guide with source citations, page count and bounds gates |
| `tools\check_docs.py` | Local documentation links, TODO status/dependencies and cycles |
| `tools\record_evidence.py` | Sanitized aggregate receipts and an explicit working-tree hash |
| `Setup-TrickRoom.ps1` | Isolated Python/dependency/model setup |
| `Start-TrickRoom.ps1` | Source-runnable desktop launcher |
| `requirements-lock.txt` | Verified Windows/Python 3.12 dependency constraints |
| `TODO\` | Stable numbered workstreams and acceptance evidence |
| `JOURNAL.md` | Technical history, including failures and limitations |

`.txt` copies of the PowerShell scripts are byte-identical sharing copies, not separate
implementations. `models\*.task`, `.venv`, `.local` and `.agent-context` are ignored.

There is no runtime dependency on another local project, an OBS install, Blender, an Azure
service, an API key or a GitHub connection.
