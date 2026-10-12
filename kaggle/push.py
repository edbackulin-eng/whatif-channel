"""Push a GPU job to Kaggle, wait for it, and pull the results back.

Kaggle gives roughly 30 GPU-hours a week on a P100 or two T4s. That is far more
than this channel needs (a video's images are minutes of GPU time), and it is the
only free way to run FLUX and Chatterbox at all on a machine with no CUDA.

Needs ~/.kaggle/kaggle.json (Kaggle > Settings > API > Create New Token).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
RESULTS = ROOT / "results"


def _notebook(job):
    """A one-cell notebook: the job dict, then the template body.

    The Hugging Face token is injected here, at submit time, and never stored in
    a job file. Those files are generated artefacts that would otherwise sit in
    the repository with a live credential in them - and this repository is
    public, so that is a leak, not an inconvenience.
    """
    from job_template import SOURCE
    job = dict(job)
    token = os.environ.get("HF_TOKEN") or _env_token()
    if token and job.get("image_prompts"):
        job["hf_token"] = token
    cell = f"JOB = {json.dumps(job, indent=2)}\n\n{SOURCE}"
    return {
        "cells": [{"cell_type": "code", "metadata": {}, "execution_count": None,
                   "outputs": [], "source": cell.splitlines(keepends=True)}],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python",
                           "name": "python3"},
            "language_info": {"name": "python", "version": "3.11.0"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }


def _env_token():
    """HF_TOKEN from .env, for local runs. In CI it arrives as a secret."""
    env = ROOT.parent / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "HF_TOKEN":
            return value.strip().strip(chr(34)).strip(chr(39)) or None
    return None


def _metadata(username, slug, title):
    return {
        "id": f"{username}/{slug}",
        "title": title,
        "code_file": "notebook.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,   # needed to pull model weights from Hugging Face
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
    }


def _run(args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result


def username():
    cfg = Path.home() / ".kaggle" / "kaggle.json"
    if not cfg.exists():
        raise SystemExit(
            "No Kaggle credentials.\n"
            "  1. kaggle.com > your avatar > Settings > API > Create New Token\n"
            f"  2. save the downloaded kaggle.json to {cfg}\n")
    return json.loads(cfg.read_text())["username"]


def _slugify(title):
    """Kaggle derives the kernel slug from the TITLE, not from the id you send.

    Passing a title that slugifies to something else silently creates the kernel
    at the other slug, and every later status/output call then fails with a
    permission error that looks like an auth problem. So the slug is computed
    from the title here and the id is made to match it.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return re.sub(r"-{2,}", "-", cleaned)


def push(job, slug, title):
    BUILD.mkdir(parents=True, exist_ok=True)
    derived = _slugify(title)
    if derived != slug:
        log_slug = slug
        slug = derived
        print(f"note: Kaggle slugifies the title, so the kernel id becomes "
              f"{slug!r}, not {log_slug!r}")
    user = username()
    (BUILD / "notebook.ipynb").write_text(
        json.dumps(_notebook(job), indent=1), encoding="utf-8")
    (BUILD / "kernel-metadata.json").write_text(
        json.dumps(_metadata(user, slug, title), indent=2), encoding="utf-8")
    out = _run([sys.executable, "-m", "kaggle", "kernels", "push", "-p", str(BUILD)])
    print(out.stdout.strip())
    return f"{user}/{slug}"


def wait(ref, poll_s=30, timeout_s=3 * 3600):
    """Block until the kernel stops running. Kaggle has no webhook, so we poll."""
    started = time.time()
    while time.time() - started < timeout_s:
        result = _run([sys.executable, "-m", "kaggle", "kernels", "status", ref],
                      check=False)
        text = (result.stdout + result.stderr).strip()
        status = text.lower()
        elapsed = int(time.time() - started)
        print(f"  [{elapsed:5d}s] {text[:110]}", flush=True)
        if "complete" in status:
            return True
        if "error" in status or "cancel" in status:
            return False
        time.sleep(poll_s)
    print("timed out waiting for the kernel")
    return False


def fetch(ref, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "kaggle", "kernels", "output", ref, "-p", str(dest)])
    files = sorted(p for p in dest.rglob("*") if p.is_file())
    print(f"\npulled {len(files)} file(s) into {dest}:")
    for f in files:
        print(f"  {f.relative_to(dest)}  ({f.stat().st_size / 1e6:.2f} MB)")
    report = dest / "report.json"
    if report.exists():
        print("\n==== report.json ====")
        print(report.read_text())
    return dest


def main():
    ap = argparse.ArgumentParser(description="run a GPU job on Kaggle")
    ap.add_argument("job_file", help="JSON file with the job spec")
    ap.add_argument("--slug", default="whatif-gpu-job")
    ap.add_argument("--title", default="WhatIf GPU job")
    ap.add_argument("--no-wait", action="store_true")
    args = ap.parse_args()

    job = json.loads(Path(args.job_file).read_text(encoding="utf-8"))
    ref = push(job, args.slug, args.title)
    print(f"pushed {ref}\nhttps://www.kaggle.com/code/{ref}")
    if args.no_wait:
        return 0
    print("\nwaiting for the run to finish...")
    if not wait(ref):
        print("kernel did not complete; check the link above")
        return 1
    fetch(ref, RESULTS / args.slug)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
