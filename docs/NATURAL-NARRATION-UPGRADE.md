# Natural narration upgrade — what was done, measured, and not done

23 October 2026. M1, 8 GB. Engines unchanged (Qwen3-TTS 0.6B 8-bit, Chatterbox v3), Hal still the default voice, Mike still present, every voice, session, take and previous export untouched (hash manifest before and after, §9).

**Read this first.** I could not listen to audio. Nothing below claims the voice now "sounds more human". What I can claim is what was measured, what was implemented and tested, and what was tried and rejected. The listening page is `samples/natural-upgrade/index.html`; it needs your ears.

The headline: **neither engine accepts a genuine delivery, emotion, emphasis or context control while cloning a voice**, so the large "expressiveness" part of the brief cannot be implemented honestly. What could be done was reliability (cut-off sentences, review of joins, export checks) plus one real, exact control (pace). Several ideas were tested and rejected on evidence; those results are as useful as the features.

## Phase A — audit

**What already worked:** two engines with per-section override; takes kept per section with manual selection; ASR verification with up to three retries; exact `[pause:]`; `{written|spoken}` / `[say:]`; staleness tracking; assembly that preserves quiet audio and decay; WAV/MP3 export; the handbook; Hal default.

**What was broken or missing** (root causes in `docs/ELEVENLABS-QUALITY-BENCHMARK.md`): the boundary check looked only at the last *sample*, so a take whose sound stops dead (14 % of Qwen3 and 24 % of Chatterbox takes; the opening question of your Whydo narration) passed; no review of how neighbouring sections fit; exports were never re-read; unsupported marks were reported only as "unknown direction".

**What the installed engines genuinely accept** (`generate()` signatures read from the installed code):

| Capability | Qwen3-TTS (Base, cloning) | Chatterbox v3 |
|---|---|---|
| Reference audio (+ transcript) | yes (`ref_audio`, `ref_text`) | audio only |
| Previous text / context argument | **none** | **none** |
| Emotion / style instruction while cloning | `instruct` exists but is **not used on the cloning path**; the VoiceDesign/CustomVoice variants take it but cannot clone | `exaggeration` (measured earlier: no reliable effect on pitch or loudness) |
| Speed | `speed` argument **not forwarded** on cloning; only the reference clip's tempo steers pace, and only upward | `speed` accepted; not used |
| Per-word emphasis | none | none |
| Sampling (`temperature`, `top_p`, `top_k`) | yes | yes — changes *which* take, not its delivery (measured) |

## Phase B — reliability (implemented and tested)

| Change | Evidence it is real |
|---|---|
| **Abrupt endings/starts are detected from energy, not the last sample.** `audio.edge_decay`/`boundary_check` report `tail_abrupt`, `head_abrupt` (thresholds calibrated on ElevenLabs and 133 takes). | Section 1 of your narration flags at −12.5 dB; the other six do not. Four diagnostic tests plus the retry regression test below. |
| **Such a take is kept but marked "needs review" and retried with another seed** (the existing three-attempt path). Nothing is deleted or replaced; the cut-off recording stays in the take list with the reason. | Regression test with a fake engine: first take stops dead → retried → second selected; first take's raw file still exists. |
| **Minimal protective ramp** (3 ms, `audio.edge_ramp`) only where a section's own sound is above −50 dBFS against the digital silence placed around it. It is applied at assembly, never to the stored take, and a flagged cut-off take stays flagged. | Tests: ramps an audible edge, leaves a naturally decaying take bit-identical, never rewrites the take file, does not hide `abrupt_end`. In your Whydo narration it fires **0** times (every edge is ≤ −57 dBFS). A fade is not presented as a fix for missing speech. |
| **Per-take quality flags** (`voice_studio/quality.py`): clipping, abrupt start/end, > 0.6 s internal silence, pace outside 1.8–5.2 words/s, loudness spread > 28 dB, repeated words (from the transcript), possible pitch jumps (note only). Stored with the take and shown as ⚠ in the take list, with the measurement in the tooltip. | 14 tests in `tests/test_quality.py` (synthetic cases built to trigger each flag, and normal takes that must stay quiet). **There is deliberately no single quality score**: it could be mistaken for "sounds natural". |
| **Join review** (new **Review** tab): for every join, loudness, typical-pitch and brightness change plus the designed gap; "Play this join" builds and plays just those two sections through the real assembler. Read-only. | On your narration: loudness consistent (−18.9 to −19.1 dB across sections), but the join into section 7 shows +7.5 semitones of typical pitch and 1.9× brightness. |
| **Export validation**: after every export the file is decoded and measured (length vs the narration, integrated loudness, true peak, clipped samples); the result is in the status line. | Run on the repaired export: −18.1 LUFS, −1.5 dBFS, 0 clipped, length matches. |
| Loudness consistency | Already good: per-section RMS normalisation puts sections within 0.2 dB; the review flags a jump above 4 dB if one ever appears. No new normalisation was added. |

## Phase C — naturalness

### Tested and **rejected** (data in `samples/natural-upgrade/experiments/`)

* **Reference clip as a delivery control.** Three reference windows of Hal's original (calm 11–24 s, a 4 s question, the 10.9 s opening) × three sentence types × five seeds = 45 takes, all word-checked (45/45 pass). A question-style reference did **not** raise pitch or widen pitch range on a question (+1.4 Hz, d = 0.12; range −2.4 semitones) and effects change sign between sentence types. The only recurring effect is +0.15 to +0.21 words/s. **This corrects the previous benchmark report**, which said the opening reference matched ElevenLabs' pitch; that was one seed per section and was noise.
* **Chaining context** (each sentence conditioned on the previous generated sentence). It is a real mechanism: the spread of per-sentence median pitch fell from 14.5 to 7.4 Hz and from 20 to 7.1 Hz (two seeds). But brightness (spectral centroid) fell about 10–25 % per step (736 → 663 → 555 Hz; 654 → 563 → 495 Hz), so the voice drifts duller and away from Hal. 3/4 words correct in three of four runs. **Not enabled.**
* **Merging sections for continuity.** Whole-script generation gave ElevenLabs-like gaps (0.33 s, SD 0.10) but two of nine endings were abrupt and it removes per-section editing. Per-sentence generation gave no gain in pitch range. Keeping paragraph-level sections (the current behaviour) is the best trade-off I could measure; I changed nothing here.
* **Breathing.** A breath-like-noise detector fired at similar rates in ElevenLabs (19.5/min), Qwen3 (17.3/min) and Chatterbox (18.9/min) because unvoiced "s"/"f" sounds trigger it too. I can neither confirm nor rule out natural breaths without listening. **No breath is inserted, removed or moved**; any breath in a recording is left alone.
* **Word emphasis, pitch contour, emotion, "curious" delivery.** No engine control exists (table above, and `docs/EXPRESSIVE-RESEARCH.md`). Raising volume or pitch would be fake emphasis and was not built.

### Implemented

* **`[pace:slow|normal|fast]`** — re-times one section by ×0.93 / ×1 / ×1.07 with the app's pitch-preserving stretch. Measured on three takes at 0.93× and 1.07×: duration changes by the amount asked (0.931–0.932 at 1.07), pitch median within 0.4 semitone, periodicity unchanged, centroid within 6 %. Adding or changing the mark needs **no new recording**: the section is re-processed from its saved raw take as a **new take**; the earlier take stays listed. It is a speed control only. Tests: parsing, conflicts, take stays non-stale, re-timing from raw without calling a model, exact stretch, idempotence.
* **Unsupported marks are refused with a reason**, left visible in the text, and block generation (`[delivery:…]`, `[emotion:…]`, `[emphasis:…]`, `[tone:…]`, `[whisper:…]`, `[breath:…]`), instead of a generic "unknown".

## Phase D — direction language and handbook

Supported before and still working: punctuation, paragraphs, `[pause:n]`, `[say:]`, `{written|spoken}`, per-section engine, section editing. Added: `[pace:]`. The handbook has a new **Speaking pace** chapter, explicit entries for refused delivery/emphasis marks and for context (with the measured reasons), and the shareable quick-start now covers pace and what not to rely on. Reliability labels are Reliable / Varies by engine / Not supported. Nothing is labelled "experimental" because nothing implemented is experimental: the only experimental mechanism (chained context) was rejected.

## Phase E — engine research (nothing downloaded or installed)

Prior evaluations (`docs/ENGINE-EVALUATION.md`, `docs/EXPRESSIVE-RESEARCH.md`) already eliminated F5-TTS (non-commercial weights), OmniVoice and Breeze-TTS-2 (non-commercial weights despite an `apache-2.0` tag), and VoxCPM2 (instruction did not survive cloning). New searches today:

| Candidate | Finding | Verdict |
|---|---|---|
| Qwen3-TTS **1.7B** Base | Documentation describes it as stronger for naturalness; reported memory 6–8 GB (sources disagree) against 2–4 GB for 0.6B. No head-to-head cloning measurement found. | On an 8 GB Mac, which already swaps heavily, it is unlikely to run comfortably. Worth a measured trial **only after you approve the download**; size to be confirmed from the model card first. Not installed. |
| **IndexTTS-2** | Zero-shot cloning with separate emotion vectors (the one design that separates identity from emotion); an MLX conversion exists (`mlx-community/IndexTTS-2-MLX`, fp32, package `mlx-indextts`, **not** mlx-audio). Weights reportedly under the Bilibili Model License with commercial thresholds that I could not read. | The only candidate that could address your expressiveness goal, but unverified licence, likely large fp32 weights, and not integrated with the installed stack. Needs your approval and a licence read before any download. |
| Kokoro-82M | Apache-2.0, fast on MLX, **no voice cloning**. | Cannot use your voices. |
| XTTS v2 | Cloning, but non-commercial licence; Mac GPU issues. | Eliminated. |
| Higgs Audio | Cloning; licence not found in results. | Previously found to have no instruct argument. |

**Recommendation:** no engine replacement is justified by measurement. If you want to pursue expressiveness, the sensible next experiment is IndexTTS-2 after a licence read and a size check, benchmarked against the same Whydo script with five seeds per setting.

## Phase F — verification

All suites ran against **cloned data** under `samples/natural-upgrade/verification/`, never `local_data/`, with network denied for the real-engine runs. Earlier evidence folders were left in place.

| Check | Result |
|---|---|
| Unit tests (`pytest`) | **186 passed, 0 failed, 0 skipped** (151 at the start of the benchmark work; 35 added since: edge diagnostics, retry, ramp, pace, refused marks, handbook copy, quality flags, join review, export validation). The suite launched with the other checks ran 172 before the quality tests were written; the final run is 186. |
| Isolated Qt widget checks | **9/9** — Hal default, VDL timing reuse, section edits, malformed directions, check labels, Handbook search, controls fit at both window sizes |
| Desktop/media check | **34 results, none false**; default voice Hal, two voices (Hal, Mike), both engines offered, take switching without regenerating, playback |
| Real-engine integration (Qwen3 → Chatterbox replacement → retime → resume → WAV/MP3 export) | **All 7 assertions true.** Qwen3 17.2 s, peak 3.62 GB; Chatterbox 77.2 s, peak 4.43 GB; retime 1.5 s and resume 0.8 s with no model load |
| Hybrid check (mixed engines, manual take selection, stale detection, both exports) | **0 failures**, peak 4.72 GB |
| Your library | hash manifest of every `local_data/` file before and after: **identical**. `Hal Voice over app.mp3` unchanged. |
| Stored quality flags on real takes | Present on every new real take (7 takes, both engines). One Qwen3 take carried an `unusual_pace` flag, which is how it is meant to appear. |

**Not verified with real audio:** no real take was cut off during these runs, so the abrupt-end retry is verified by a regression test with a fake engine (first take stops dead, second finishes, first take's recording kept), and by the real take of your narration that the detector flags at −12.5 dB, not by a live retry on a real cut-off take. The `[pace:]` re-timing is verified on a fixture and measured on three real takes, not yet heard.

Memory on 8 GB: unchanged from before this work, peak 3.6 GB (Qwen3) and 4.4 GB (Chatterbox) with one engine loaded; the review, quality flags and export validation add about 0.1 GB resident and under a second.

## What was not done, and why

* Delivery, emotion, emphasis, pitch-contour and word-stress controls — no genuine mechanism on either engine.
* Context conditioning — mechanism exists but degrades the voice (above).
* Section merging, breath insertion/removal, automatic crossfades (a crossfade overlaps words; sections are separated by silence by design), cross-section EQ or loudness "flattening".
* A separate **Export** tab: export is one button plus a check; a tab would add navigation without adding capability. The **Review** tab was added because it holds new information.
* Switching or adding an engine.

## Remaining limitations

* The listening quality of everything above is unjudged; the flags show where to listen.
* Pace is ±7 % only and does not add expression.
* The review's pitch/brightness joins use a coarse tracker; a flag is a reason to listen.
* Takes recorded before this change have no stored quality flags (they are computed for new takes) and, if older still, no raw file to re-time.
* Retrying abrupt endings costs time (about 13 % more generations for Qwen3 and 24 % for Chatterbox on average, up to three attempts).

## Recommendations

1. Listen to `samples/natural-upgrade/index.html` (groups 1 and 5 first) and tell me whether the flagged join into section 7 is audible.
2. Make **Natural** your default style for narration: it matches ElevenLabs' pace (3.14 vs 3.10 words/s); Energetic Explainer is 19 % faster with no wider pitch range.
3. Regenerate sections the review flags rather than processing them.
4. If expressiveness is the goal, authorise a licence read and size check for IndexTTS-2.

Sources: [mlx-audio](https://github.com/Blaizzy/mlx-audio) · [Qwen3-TTS model overview](https://www.mintlify.com/QwenLM/Qwen3-TTS/concepts/models) · [Qwen3-TTS FAQ](https://www.mintlify.com/QwenLM/Qwen3-TTS/resources/faq) · [IndexTTS-2 MLX](https://huggingface.co/mlx-community/IndexTTS-2-MLX) · [IndexTTS2 overview](https://tts.ai/voices/indextts2/)
