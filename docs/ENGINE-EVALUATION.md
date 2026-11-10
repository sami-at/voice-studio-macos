# Expressive TTS engine evaluation

Measured on this machine (Apple M1, 8 GB, macOS 26.6.2) on 20 October 2026. Nothing in the
application was changed. The current engine, the voice profiles, and every saved narration are
exactly as they were; the candidates live in `models/evaluation/` and are not wired to anything.

## Verdict first

**Keep the current engine. Do not switch to Chatterbox.** The expressive control that justified
the whole exercise could not be shown to work, and the cost is a 6.5x slowdown.

## 1. Which candidates survived the requirements

Your requirements were: free, offline, 8 GB, English, **your own reference voices**, and
**commercially usable**. Two candidates were eliminated before benchmarking, on evidence.

| Model | Cloning | Instruction control | Outcome |
| --- | --- | --- | --- |
| Qwen3-TTS **Base** (current) | yes | no | In use. `instruct` is rejected by the checkpoint. |
| Qwen3-TTS **VoiceDesign** | **no** | yes | **Eliminated.** Fails "use authorized reference voices". |
| Qwen3-TTS **CustomVoice** | **no** | yes | **Eliminated.** Preset speakers only. |
| **F5-TTS** | yes | no | **Eliminated on licence.** Weights are CC-BY-NC-4.0. |
| **Chatterbox Turbo** | yes | **ignored** | **Eliminated.** Prints "exaggeration not supported by Turbo". |
| **Chatterbox multilingual v3** | yes | `exaggeration`, `cfg_weight` | **Benchmarked in full.** |

### The Qwen3-TTS trap you warned about

You asked me not to assume cloning and instruction control ship together. They do not. In the
installed library, the three Qwen3-TTS variants are mutually exclusive by signature:

- `generate_voice_design(text, instruct, ...)` — **no `ref_audio` parameter at all.** The voice is
  defined entirely by the text description.
- `generate_custom_voice(text, speaker, instruct, ...)` — takes a **preset speaker name**, not a
  recording.
- The base path is the only one that accepts `ref_audio` + `ref_text`, and its own docstring says
  *"Base models have no preset voices — use ref_audio + ref_text to clone a voice instead."*

So on Qwen3-TTS you may have **your voice** or **instruction control**, never both. Mike and Hal
cannot be carried into VoiceDesign or CustomVoice.

### F5-TTS: a licence wall

The official weights (`SWivid/F5-TTS`) are **CC-BY-NC-4.0 — non-commercial**. The MLX ports
carry an MIT licence on the *code*, but they are conversions of those same weights, so the
non-commercial restriction follows the model. It fails your commercial-use requirement outright
and was not benchmarked.

## 2. Measured results

Identical five-line script, same voice (Mike), each engine in its own process. Neither was ever
in memory at the same time as the other.

| | **Current — Qwen3-TTS 0.6B 8-bit** | **Chatterbox multilingual v3** |
| --- | --- | --- |
| Audio produced | 20.9 s | 20.8 s |
| Generation time | **29 s** | **188 s** |
| Speed | **1.4x real time** | **9.1x real time** |
| Peak memory | **3.84 GB** | 4.51 GB |
| Model resident | 2.06 GB | 3.27 GB |
| Load, warm | 8.2 s | 3.8 s |
| Load, first ever | ~12 s | **196 s** |
| Install size | 2.0 GB | 3.0 GB (incl. S3 tokenizer) |
| Word completeness | **5 of 5 lines, mean coverage 0.988** | 4 of 5, mean coverage 0.961 |
| Cloning margin (Mike over Hal) | +0.155 | +0.169 |
| Licence | Apache-2.0 | MIT |
| Offline after install | yes | yes |

**What a 45-second narration costs:** about **31 seconds** today, against roughly **7 minutes**
on Chatterbox. On a machine that already swaps at idle, that is the difference between a usable
tool and one you walk away from.

Both fit in 8 GB. Chatterbox's 4.51 GB peak is below this M1's 5.73 GB Metal working set, so it
is feasible — just slow.

## 3. Expressive control: the evidence

This was the whole reason to look. Chatterbox takes `exaggeration` and `cfg_weight` alongside
`ref_audio`, which is structurally what Qwen3-TTS Base cannot do.

A single take per level looked promising — pitch spread 3.41 → 3.90 semitones from exaggeration
0.25 to 1.00. **Three seeds per level reversed it:**

| exaggeration | pitch spread, mean of 3 | individual takes |
| --- | --- | --- |
| 0.25 | **4.85** | 3.86, 4.85, 5.83 |
| 0.60 | 4.59 | 3.81, 3.83, 6.12 |
| 1.00 | **4.16** | 3.45, 4.18, 4.86 |

Expressiveness measured **lower** at maximum exaggeration than at minimum, the takes overlap
completely, and no high take cleanly beat the low ones. Loudness variation showed no trend
either (4.82 → 4.48 → 4.66 dB). This is the same pattern as every knob on the current engine:
seed-to-seed variation swamps the setting.

**The honest caveat.** `exaggeration` is a learned emotion-intensity embedding. My measures —
pitch spread and loudness variation — may simply not capture what it changes; it could be
altering voice quality or intensity in ways these numbers miss. I cannot settle that with
statistics, and you said as much yourself. **So listen before accepting my conclusion:**

```
samples/engines/chatterbox_exag25_s11.mp3   ← least exaggeration
samples/engines/chatterbox_exag60_s11.mp3
samples/engines/chatterbox_exag100_s11.mp3  ← most exaggeration
```
(seeds `s22` and `s33` are there too, and the difference between seeds is the thing to notice.)

If you hear a consistent, intended difference that my measurements missed, say so and I will
reopen this.

## 4. Side-by-side narration samples

Same five lines, same voice, both engines — a curious question, a surprising fact, a
conversational explanation, a line needing emphasis, and a calm conclusion:

```
samples/engines/current_1-question.mp3      samples/engines/chatterbox_1-question.mp3
samples/engines/current_2-surprise.mp3      samples/engines/chatterbox_2-surprise.mp3
samples/engines/current_3-explain.mp3       samples/engines/chatterbox_3-explain.mp3
samples/engines/current_4-emphasis.mp3      samples/engines/chatterbox_4-emphasis.mp3
samples/engines/current_5-conclusion.mp3    samples/engines/chatterbox_5-conclusion.mp3
```

Your judgement on naturalness decides this, not mine. What I can report objectively: Chatterbox
clones Mike about as well as the current engine (+0.169 against +0.155 separation from Hal), and
it dropped more words — one of five lines fell below the completeness floor at 0.875 coverage,
where the current engine passed all five.

## 5. Licences

| Model | Licence | Commercial use |
| --- | --- | --- |
| Qwen3-TTS 0.6B Base (current) | Apache-2.0 | Permitted |
| Chatterbox / Chatterbox multilingual v3 | MIT | Permitted |
| Chatterbox Turbo | MIT upstream, Apache-2.0 on the MLX conversion | Permitted |
| Qwen3-TTS CustomVoice / VoiceDesign | Apache-2.0 | Permitted, but cannot clone your voices |
| **F5-TTS** | **CC-BY-NC-4.0** | **Not permitted** |

Model licences never cover the **voices**. Mike and Hal remain subject to their own
authorisation notes, which are unchanged and still flag that their ElevenLabs licence is
unverified.

## Outcome: both engines, chosen per section

You listened, found neither consistently better, and asked for manual per-section choice. That
is what shipped — see *Two engines, your choice per section* in the README. Chatterbox is now a
selectable second engine, never an automatic one, and Qwen3-TTS remains the default. The
sections below are the original evaluation, kept as the record of why.

## 6. Recommendation

**Stay on Qwen3-TTS 0.6B Base.** It is 6.5x faster, uses less memory, loses fewer words, is
Apache-2.0, and is already stable. Chatterbox would cost all of that in exchange for an
expressive control I could not demonstrate working.

I am **not** proposing the two-engine switch at this point. Adding a "Expressive Engine" option
would mean a second model path, a second set of generation parameters, more settings and more
documentation — and on the evidence the user-visible benefit is unproven. That is a decorative
feature with a maintenance cost, which is exactly what you asked me to avoid.

## 7. If you want it anyway

Should you listen to the samples and disagree, the integration is modest and reversible, because
the worker already isolates the model behind one function:

1. Store `engine` on each voice profile and each narration, defaulting to `standard`.
2. In `voice_studio/worker.py`, branch at the single `load_model` / `model.generate` call;
   Chatterbox needs `ref_audio` + `exaggeration` and no `ref_text`.
3. Add `exaggeration` to `styles.py` as an engine-specific control, shown only when the
   expressive engine is selected.
4. Move `models/evaluation/chatterbox-multilingual-v3` and `S3TokenizerV2` into `models/`, and
   add them to `models.lock.json` with pinned revisions.
5. Set a generous worker timeout: the current 1800 s covers a 3-minute narration today but only
   about 25 seconds of Chatterbox output.

Fingerprints, completeness verification, retries, assembly and export are all engine-agnostic and
would carry over unchanged.

## 8. Disk

The candidates occupy **3.4 GB** in `models/evaluation/`:

```
models/evaluation/chatterbox-multilingual-v3   2.5 GB
models/evaluation/S3TokenizerV2                472 MB
models/evaluation/chatterbox-turbo-4bit        398 MB
```

Nothing references them. Say the word and I will delete them; I have left them in place so you
can listen and re-test without a second download.
