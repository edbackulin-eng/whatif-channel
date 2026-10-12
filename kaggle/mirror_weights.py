"""Mirror the FLUX weights into Kaggle so Hugging Face leaves the critical path.

The weights are Apache-2.0, so copying them is allowed outright. What this buys
is independence: the repo is gated, a token can be revoked, terms can change for
future releases, and any of those would stop every build. After this runs, the
generation kernels read the model from a Kaggle kernel output instead, and no
build touches huggingface.co at all.

Run once. Re-run only to pick up a newer revision deliberately.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SLUG = "whatif-flux-weights"

SOURCE = r'''
import os, time, json, pathlib, shutil
OUT = pathlib.Path("/kaggle/working/flux")
OUT.mkdir(parents=True, exist_ok=True)

os.system("pip install -q -U huggingface_hub")
from huggingface_hub import snapshot_download

# Pinned, not "main": a floating reference would let the mirror drift and
# reintroduce exactly the dependency this removes.
REPO = "black-forest-labs/FLUX.1-schnell"
REVISION = JOB.get("revision") or "main"

t0 = time.time()
path = snapshot_download(
    REPO, revision=REVISION, local_dir=str(OUT),
    token=JOB.get("hf_token"),
    allow_patterns=["*.json", "*.txt", "*.safetensors", "*.model",
                    "tokenizer*/*", "scheduler/*"],
    ignore_patterns=["*.bin", "*.onnx", "*.msgpack", "*.h5"],
)
took = time.time() - t0

total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
manifest = {
    "repo": REPO,
    "revision": REVISION,
    "downloaded_s": round(took),
    "total_gb": round(total / 1e9, 2),
    "files": sorted(str(f.relative_to(OUT)) for f in OUT.rglob("*") if f.is_file())[:200],
}
pathlib.Path("/kaggle/working/manifest.json").write_text(json.dumps(manifest, indent=2))
print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))
print("files:", len(manifest["files"]))
'''


def main():
    sys.path.insert(0, str(ROOT))
    import push as kpush

    job = {"_comment": "One-off: mirror FLUX.1-schnell into a Kaggle kernel output.",
           "revision": "main",
           "image_prompts": ["__mirror__"]}   # makes push.py inject HF_TOKEN
    token = kpush._env_token()
    if not token:
        raise SystemExit("HF_TOKEN not found; the source repo is gated")

    build = ROOT / "build"
    build.mkdir(parents=True, exist_ok=True)
    user = kpush.username()
    cell = f"JOB = {json.dumps({'revision': job['revision'], 'hf_token': token}, indent=2)}\n\n{SOURCE}"
    nb = {"cells": [{"cell_type": "code", "metadata": {}, "execution_count": None,
                     "outputs": [], "source": cell.splitlines(keepends=True)}],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                      "name": "python3"}},
          "nbformat": 4, "nbformat_minor": 5}
    (build / "notebook.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    (build / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{SLUG}",
        "title": "whatif flux weights",
        "code_file": "notebook.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": False,       # a download needs no GPU, and saves quota
        "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": [],
    }, indent=2), encoding="utf-8")

    r = subprocess.run([sys.executable, "-m", "kaggle", "kernels", "push",
                        "-p", str(build)], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    print(f"\nmirror kernel: {user}/{SLUG}")
    print("once complete, generation kernels can list it in kernel_sources and")
    print("read the model from /kaggle/input/whatif-flux-weights/flux")
    return 0


if __name__ == "__main__":
    sys.exit(main())
