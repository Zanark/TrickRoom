"""Assemble aggregate verification receipts; never copy input media, URLs with auth or landmarks."""

from __future__ import annotations

import hashlib
import json
import platform
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from check_docs import check

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record() -> None:
    destination = ROOT / "docs" / "evidence"
    destination.mkdir(parents=True, exist_ok=True)
    tests = ET.parse(ROOT / ".local" / "unit-results.xml")
    suites = list(tests.getroot().iter("testsuite"))
    counts = {
        key: sum(int(s.attrib[key]) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    assert counts["failures"] == counts["errors"] == counts["skipped"] == 0
    inputs = {
        "actual_inference": ROOT / ".local" / "fixtures" / "inference-report.json",
        "stream": ROOT / ".local" / "stream-check" / "loopback-report.json",
        "native_ui": ROOT / ".local" / "ui-check" / "studio-report.json",
        "reference_avatar": ROOT / "docs" / "images" / "avatar" / "avatar-manifest.json",
        "perspective_room": ROOT / "docs" / "images" / "room" / "room-manifest.json",
        "blender_runtime": ROOT / ".local" / "blender-conformance" / "blender-runtime-report.json",
        "blender_ui": ROOT / ".local" / "blender-ui" / "model-studio-report.json",
        "blender_stream": ROOT / ".local" / "blender-stream" / "loopback-report.json",
        "authoring_handbook": ROOT / "docs" / "book" / "edition-manifest.json",
        "handbook_browser": ROOT / ".local" / "handbook-review" / "html-report.json",
        "blender_exports": ROOT / "examples" / "blender" / "conformance-build.json",
        "private_debug_ui": ROOT / ".local" / "debug-views" / "debug-ui-report.json",
        "detected_debug_points": ROOT / ".local" / "debug-views" / "actual-points-report.json",
        "auth_defaults_ui": ROOT / ".local" / "debug-views" / "auth-ui-report.json",
        "motion_upgrade": ROOT / "docs" / "evidence" / "motion-upgrade-validation.json",
        "recorded_video_view": ROOT / "docs" / "evidence" / "recorded-video-view-validation.json",
        "imported_scale": ROOT / "docs" / "evidence" / "imported-scale-validation.json",
        "collapsible_sections": ROOT / "docs" / "evidence" / "collapsible-sections-validation.json",
        "replay_timeline": ROOT / "docs" / "evidence" / "replay-timeline-validation.json",
        "motion_ui": ROOT / ".local" / "motion-upgrade" / "motion-studio.json",
        "studio_responsiveness": ROOT
        / "docs"
        / "evidence"
        / "studio-responsiveness-validation.json",
        "cli_video_export": ROOT / "docs" / "evidence" / "cli-video-export-validation.json",
    }
    source_files = sorted(
        [
            *ROOT.glob("*.toml"),
            *ROOT.glob("*.ps1"),
            ROOT / "requirements-lock.txt",
            *ROOT.joinpath("src").rglob("*.py"),
            ROOT / "src" / "trickroom" / "face_topology.json",
            ROOT / "src" / "trickroom" / "face_topology.LICENSE",
            *ROOT.joinpath("tests").rglob("*.py"),
            *ROOT.joinpath("tools").rglob("*.py"),
            *ROOT.joinpath("tools").rglob("*.cjs"),
            ROOT / "docs" / "book" / "package.json",
            ROOT / "docs" / "book" / "package-lock.json",
            ROOT / "docs" / "book" / "puppeteer.json",
            *ROOT.joinpath("docs", "book", "diagrams").glob("*.mmd"),
        ]
    )
    source_hashes = {path.relative_to(ROOT).as_posix(): digest(path) for path in source_files}
    source_digest = hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest()
    receipt = {
        "recorded_at": datetime.now().astimezone().isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "source": {
            "kind": "uncommitted-working-tree",
            "sha256": source_digest,
            "files": source_hashes,
        },
        "unit_tests": counts,
        "unit_test_modules": sorted(
            {case.attrib["classname"] for case in tests.getroot().iter("testcase")}
        ),
        "docs": check(),
        "receipts": {
            key: json.loads(path.read_text(encoding="utf-8")) for key, path in inputs.items()
        },
        "carried_forward_receipts": [
            "actual_inference",
            "stream",
            "reference_avatar",
            "perspective_room",
            "blender_runtime",
            "blender_stream",
            "blender_exports",
            "detected_debug_points",
            "auth_defaults_ui",
            "motion_upgrade",
            "recorded_video_view",
            "imported_scale",
            "collapsible_sections",
            "replay_timeline",
            "studio_responsiveness",
            "native_ui",
            "blender_ui",
            "private_debug_ui",
            "motion_ui",
        ],
        "boundaries": {
            "owner_camera_tested": False,
            "real_motion_recording_tested": True,
            "ground_truth_accuracy_improvement_demonstrated": False,
            "user_visual_approval_obtained": False,
            "physical_camera_to_display_latency_measured": False,
            "final_reference_art_rig_built": False,
            "technical_blender_conformance_rigs_built": True,
            "raw_camera_media_committed": False,
        },
    }
    (destination / "prototype-validation.json").write_text(
        json.dumps(receipt, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Saved aggregate evidence for source tree {source_digest}")


if __name__ == "__main__":
    record()
