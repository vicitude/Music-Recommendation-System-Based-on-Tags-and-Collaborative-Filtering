# Local CLAP installation and bounded probe

Production opt-in worker: `clap_minimum_batch.py` uses the approved minimum-label policy in the isolated environment, up to five inputs via stdin. Django recomputes decisions from raw scores before explicit user confirmation can save new draft tags. Existing songs are never overwritten by this import route. See `docs/B3-多标签批量预览保存操作说明.md`.

Minimum-label pilot: `clap_multilabel_run.py --minimum-remaining --output local-ai/diagnostics/NEW.json` runs the remaining 25 songs using unchanged multilabel prompts. `clap_minimum.py` adds marked LOW_FALLBACK labels only for missing dimensions after quality/music controls; scenes are rule suggestions. Limits are 1–2 style, 1–3 mood, 1–2 scene. No production/database changes. See `docs/B2-每类至少一个离线契约.md`.

Reference foundation: `clap_reference.py prepare` deterministically selects 12 baseline songs without prediction-based selection and audits existing local genre/mood metadata with FFprobe. Evidence remains PENDING; embedded metadata is not truth. `evaluate` requires identity-bound independent provenance, separates partial UNKNOWN from complete negatives, and returns null metrics without verified references. See `docs/B2-标签参考集契约.md` and `docs/B2-标签参考集准备报告.md`. No database, production tags or model inference involved.

Sampling comparison: `clap_sampling_compare.py` compares original boundary/middle sampling against 20/50/80 percent of the valid start interval using unchanged production prompts and gates. The independent process temporarily replaces and restores the worker sampling function; no production file is edited. It validates source fingerprints, historical and repeated-middle controls, refuses overwrites, and supervises total/no-progress timeouts. See `docs/B2-取样位置对照方案.md` and `docs/B2-取样位置对照报告.md`.

Prompt comparison: `clap_prompt_compare.py` runs in the independent model environment against the fixed completed 40-song baseline. It reuses each audio embedding for original and style-only symmetric prompts, verifies historical score reproduction within 0.0001, keeps mood/control scores identical, and refuses output overwrite. No production prompt, database or tag changes. Results and bounded execution requirements: `docs/B2-描述词对照方案.md` and `docs/B2-描述词对照报告.md`.

Full-catalog diagnosis: run `clap_diagnose.py` with the backend virtual environment, `--source` set to the approved material directory and `--output` inside ignored `local-ai/diagnostics`. It uses test settings without querying a database, selects all structurally valid files, calls the unchanged offline model worker in groups of five and checkpoints scores/diagnostic gate failures. It never creates an admin import batch or writes song tags. Results measure coverage/stability, not accuracy; preserve model/policy/prompt versions when comparing runs.

Batch integration: `clap_batch.py` is an offline stdin/stdout worker launched by Django using the independent interpreter. `clap_policy.py` contains versioned prompts, non-overlapping segment positions, and conservative review-only selection. Up to five songs per request, three ten-second segments per song. Results are not probabilities and never authorize automatic tag writes. See `specs/music/system/clap-candidates-contract.md` and `docs/B2-CLAP多片段候选操作说明.md`.

These utilities are separate from Django. They do not import its settings, access MySQL, copy source songs, or write tags.

## Approved environment

- Existing CPython 3.12, independent virtual environment.
- CPU PyTorch 2.8.0+cpu, Transformers 4.57.6, NumPy 2.2.6, SciPy 1.15.3.
- Model: `laion/clap-htsat-fused`, Apache-2.0 as declared by its official model card.
- Pinned revision: `365dea6ef167def6676140ed93bbc43f84dabb28`.
- Only the safetensors weights are downloaded, not pickle weights or custom model code.
- Model weights: 614,496,152 bytes, SHA256 `3f648de6d030e17494be455d323b8d191233fbae0c7ce0ba745fd21a926a63a6`.
- Official CPU wheel: 619,352,539 bytes, SHA256 `2be20b2c05a0cce10430cc25f32b689259640d273232b2de357c35729132256d`.

## Locations and usage

Default model/download home: `<project>/local-ai`, ignored by Git, overridden with `MUSIC_AI_HOME` or the probe's `--home`. The model files have been moved into this project directory at the user's request. The independent Python environment remains at `C:/Users/will vicissitude/AppData/Local/MusicRecommenderAI/clap-venv`; Python virtual environments are not relocated by copying. The original CPU wheel and prior logs/reports remain on C:, outside the model directory. A quarantined checksum-mismatch weight is retained alongside the model, never loaded, pending separately approved cleanup.

Create `clap-venv` with the existing Python 3.12 and install the four packages above using CPU-only PyTorch from its official index. `clap_install.py` verifies the pinned CPU wheel and installs it, then downloads the pinned model's configuration/tokenizer and safetensors files into `models/clap-htsat-fused`. It writes a private installation manifest and checks dependencies. It never installs into the project's `.venv`.

Run `clap_probe.py` with the independent environment's Python, explicit `--home`, and up to five `--audio` paths. The probe reads ten seconds per song through existing FFmpeg, generates a synthetic tone control, loads local weights only, and prints fixed-prompt cosine rankings. Optional `--output` stores a local diagnostic report; put that outside Git as it contains song filenames. This is not a production auto-tagger: ranking always has a top item even for the synthetic tone. No probability, confidence threshold, accuracy claim or automatic tag application is provided.

Do not commit environments, weights, logs, package caches, reports or private installation manifests. Recheck model/code licensing and provenance if changing revisions. This installation does not authorize future framework upgrades or alternative checkpoints.
