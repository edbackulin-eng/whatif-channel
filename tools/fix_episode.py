"""Repair black stretches in a built package, re-run QC, and say what is left.

    python tools/fix_episode.py ready/<date>/<slug>

Rewrites video.mp4 and qc.json in place when a repair was made. Exit 0 when the
package now passes QC, 1 when anything still needs a look.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import autofix, qc  # noqa: E402


def main(pkg):
    pkg = Path(pkg)
    video = pkg / "video.mp4"
    fix = autofix.repair(video, pkg / "video_fixed.mp4", pkg / "_autofix")
    autofix.write(fix, pkg / "autofix.json")
    print(json.dumps(fix, indent=1))
    if fix["covered"] and abs(fix["duration_out"] - fix["duration_in"]) < 0.1:
        shutil.move(str(pkg / "video_fixed.mp4"), str(video))
    shutil.rmtree(pkg / "_autofix", ignore_errors=True)
    report, problems = qc.check_video(video, thumbnail_path=pkg / "thumbnail.png",
                                      srt_path=pkg / "subs.srt",
                                      expected_min_s=16 * 60, expected_max_s=26 * 60)
    verdict = qc.write_report(pkg / "qc.json", report, problems)
    print("QC:", verdict["verdict"], problems, "| video", report.get("video_mbps"), "Mbit/s,",
          report.get("resolution"))
    return 0 if verdict["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
