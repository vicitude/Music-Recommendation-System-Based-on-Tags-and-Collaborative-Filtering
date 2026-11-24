import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from uuid import uuid4


ROOT = Path(os.environ.get("MUSIC_AI_HOME", Path(__file__).resolve().parents[1] / "local-ai"))
REVISION = "365dea6ef167def6676140ed93bbc43f84dabb28"
MODEL = "laion/clap-htsat-fused"
TORCH_URL = "https://download-r2.pytorch.org/whl/cpu/torch-2.8.0%2Bcpu-cp312-cp312-win_amd64.whl"
TORCH_HASH = "2be20b2c05a0cce10430cc25f32b689259640d273232b2de357c35729132256d"


def download(url, target, expected_hash=None):
    if target.is_file():
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if not expected_hash or actual == expected_hash:
            return
        raise RuntimeError("Existing file checksum mismatch: " + target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name("temp_" + uuid4().hex + "_" + target.name + ".partial")
    digest = hashlib.sha256()
    count = 0
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
            count += len(chunk)
            if count % (50 * 1024 * 1024) == 0:
                print(target.name, count, flush=True)
    if expected_hash and digest.hexdigest() != expected_hash:
        raise RuntimeError("Downloaded file checksum mismatch: " + target.name)
    os.replace(partial, target)
    print("Verified", target.name, count, flush=True)


def main():
    wheel = ROOT / "downloads/torch-2.8.0+cpu-cp312-cp312-win_amd64.whl"
    download(TORCH_URL, wheel, TORCH_HASH)
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--only-binary=:all:", str(wheel)], check=True)
    url = "https://huggingface.co/api/models/" + MODEL + "/revision/" + REVISION + "?blobs=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        metadata = json.load(response)
    if metadata.get("cardData", {}).get("license") != "apache-2.0":
        raise RuntimeError("Unexpected model license")
    model_root = ROOT / "models/clap-htsat-fused"
    allowed = {"README.md", "config.json", "preprocessor_config.json", "merges.txt", "vocab.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "model.safetensors"}
    manifest = {"model_id": MODEL, "revision": REVISION, "license": "apache-2.0", "files": []}
    for entry in metadata["siblings"]:
        name = entry["rfilename"]
        if name not in allowed:
            continue
        expected = entry.get("lfs", {}).get("sha256")
        target = model_root / name
        download("https://huggingface.co/" + MODEL + "/resolve/" + REVISION + "/" + name, target, expected)
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest["files"].append({"name": name, "bytes": target.stat().st_size, "sha256": actual})
    (model_root / "installation-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    print("INSTALLATION_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
