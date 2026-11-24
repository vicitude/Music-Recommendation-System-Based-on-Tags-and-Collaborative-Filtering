import json
import sys

import torch
import clap_batch
from clap_minimum import VERSION, decide_minimum
from clap_multilabel import texts
from clap_policy import MODEL_ID, REVISION
from clap_sampling_compare import internal_starts
from pathlib import Path


def main():
    request = json.loads(sys.stdin.buffer.read(65537).decode("utf-8"))
    items = request["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 5:
        raise ValueError("Expected 1 to 5 inputs")
    directory = Path(request["home"]) / "models/clap-htsat-fused"
    manifest = clap_batch.verify_weights(directory)
    if manifest["model_id"] != MODEL_ID or manifest["revision"] != REVISION:
        raise ValueError("Model mismatch")
    torch.set_num_threads(4)
    processor = clap_batch.ClapProcessor.from_pretrained(directory, local_files_only=True)
    model = clap_batch.ClapModel.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    with torch.inference_mode():
        inputs = processor(text=texts(), return_tensors="pt", padding=True)
        embeddings = torch.nn.functional.normalize(model.get_text_features(**inputs), dim=-1)
    clap_batch.segment_starts, clap_batch.decide_candidates = internal_starts, decide_minimum
    results = [clap_batch.analyze_item(item, model, processor, embeddings, request["ffmpeg"]) for item in items]
    print(json.dumps(dict(model_id=MODEL_ID, revision=REVISION, policy_version=VERSION, prompts_version="multilabel-neutral-v1", mapping_version="formal53-multilabel29-v1", results=results), ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
