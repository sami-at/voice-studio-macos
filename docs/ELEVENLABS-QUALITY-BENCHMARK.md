# Voice Studio vs ElevenLabs Hal — quality benchmark

23 October 2026. **Status: findings and listening files only. Nothing here has been approved by ear, and nothing in the app's audio path has been changed beyond a diagnostic.** Open [`samples/elevenlabs-benchmark/index.html`](../samples/elevenlabs-benchmark/index.html) and listen before deciding anything.

I could not listen to audio while doing this. Every statement below is a measurement or a controlled A/B on the same inputs; none of it shows that a voice sounds natural, human or pleasant. Where a number says two recordings differ, the page lets you check whether you can hear it.

## What was compared

| | File | Evidence it is what you described |
|---|---|---|
| Reference | `~/Downloads/ElevenLabs_2026-10-23T19_00_04_Hal - Your Animated Social Media Buddy_pvc_sp104_s32_sb34_v4.mp3` | Filename is ElevenLabs' own export pattern, voice "Hal"; 44.1 kHz, 128 kbps, 43.15 s |
| Under test | `~/Downloads/Hal Voice over app.mp3` | 48 kHz, 320 kbps (Voice Studio's export settings), 38.2275 s. **Decodes to the same samples (difference −153 dB) as a fresh export of `local_data/sessions/b3daa…/narration-repaired.wav`** — the session titled "Whydo flies — Energetic repaired" — so it is exactly the app's output |

These are the two newest MP3s by modification time (19:01 and 18:58). Both originals are byte-identical to before (SHA-256 in `samples/elevenlabs-benchmark/audio/originals/SHA256.txt`; verified again at the end). `Flies WhyDo.mp3` (12:24) looks like an earlier export and was not used.

Two facts that shape everything else:

* The Hal **reference clip** Voice Studio clones from is itself an ElevenLabs recording (11.0–24.06 s of a 24.3 s MP3). The benchmark is therefore ElevenLabs imitating itself, versus a 0.6 B open model cloning a 13-second excerpt of it.
* Your file is assembled from **seven sections taken from different seeds** (1996, 3044, 2046, 46, 1024, 48, 49); sections 2 and 3 are a single merged take, and two selected takes are flagged `verified: False` in the project. It is a curated take set, not a single run.

## 1. Defects reproduced

| # | Finding | Evidence |
|---|---|---|
| 1 | **The opening question stops abruptly.** "…planning something?" ends with a voiced burst that is cut at full strength; ElevenLabs fades out over ~150 ms. | The last audible 5 ms block is only 8.8 dB below the preceding speech in your MP3 (12.5 dB in the raw take). ElevenLabs' nine phrase endings fall 16.5–38.9 dB (median 25.8). Spectrogram of the last 0.4 s shows formants intact up to the cut. |
| 2 | **This happens in other takes too.** | Over 133 raw takes on disk, **13 % of Qwen3 and 24 % of Chatterbox** takes end with < 15 dB of decay. 17 % of Qwen3 takes also begin at near full level (first audible block within 6 dB of the speech that follows). |
| 3 | **The app could not see it.** `boundary_check` examined only the final *sample*, which is ~0 even when a sound stops dead (the decoders pad with near-silence). Section 1 was reported "no boundary problem". | Reproduced on the real take; fixed as a diagnostic (§3). |
| 4 | **Duller upper range.** Relative to the 1 kHz octave, ElevenLabs keeps 2.5 kHz at +1.0 dB and 4/6.3/9 kHz at −2.5/−3.2/−4.6 dB, matching the Hal reference clip (−0.2/−4.5/−4.0/−5.7). Voice Studio is −2.4/−6.9/−8.0/−9.5; raw Qwen3 and Chatterbox are −10 to −13 dB at 6–9 kHz. Spectral centroid 797 Hz vs 1084 Hz. | Octave bands over the louder 40 % of frames. Content stops near 11–12 kHz (24 kHz engines) against ~15 kHz for ElevenLabs. |
| 5 | **Faster and less evenly paced.** | Speech rate 3.59 words/s vs 3.10 (+16 %), up to +38 % on "It looks a little suspicious…" (4.11 vs 2.97). Sentence gap SD 0.18 s vs 0.06 s; the gap before "They're just keeping…" is 0.08 s against 0.29 s. |
| 6 | **Narrower pitch movement.** | Per-phrase 5–95 % F0 range 16.4 vs 18.8 semitones; 12.0 vs 21.1 on the "suspicious" sentence. |
| 7 | **Digital silence between phrases.** 6.8 % of frames are exact zeros; ElevenLabs never is (floor ≈ −80 dBFS). | Whether this is audible depends on your playback chain (some Bluetooth devices gate on digital silence). **Hypothesis, untested on your hardware** — see the experimental file. |
| 8 | **Take-to-take variance.** Identical text, settings and reference, eight seeds: 3.68–4.64 s long (26 % spread); 2 of 8 end abruptly. | `data/repair-choice.json`. |

### Looked for and **not** reproduced

* **Clicks at section joins.** Every seam edge sample is exactly 0.000000; edges sit at digital silence. A generic click detector fired 332 times on ElevenLabs and 340 on Voice Studio — it was triggering on fricatives and pitch pulses (inspected: a "cluster" at 2.0 s is an ordinary *z*), which is why detector counts were not used as evidence.
* **Hard-edge pops.** Edge samples are tiny, but the high-frequency content at a cut is the real measure: in your narration every take edge is ≤ −57 dBFS (≥ 35 dB under speech) — very unlikely to be audible. Some other takes reach −37 dBFS (one Qwen3 head, 26 of 87 above −60 dBFS). *Reproduced, not shown to be audible here.*
* **Loudness-normalisation damage.** `loudnorm` applied a constant +1.46 dB (SD 0.08 dB between sections). No pumping, no compression. Output −18.0 LUFS vs −18.6 for ElevenLabs; peaks −1.5 vs −1.6 dBFS; no clipping.
* **Time-stretch damage.** 1.04× `atempo` conserves energy (within +0.1 to +0.15 dB of expectation), drops nothing, and leaves a periodicity proxy unchanged (7.90 → 7.84 dB). Conditioning on the 1.15× stretched reference also left the reference's texture unchanged (10.3 → 10.1 dB).
* **MP3 damage.** 320 kbps decode vs exact WAV: error 68 dB below signal, no clipped samples, zero delay.
* **Chunk-join artefacts from streaming** (2.0 s chunks concatenated without crossfade): 2.0 s joins vs ordinary frame edges, median 1.12 vs 0.90, p = 0.036 over 107 joins — not meaningful.
* **Level or roughness difference by simple proxies.** The coarse periodicity proxy was 7.4 dB (ElevenLabs) vs 7.8 dB (Voice Studio): it does not distinguish them, so I make **no claim about "roughness"** beyond what you hear.
* **Pronunciation.** Qwen3 words match the script exactly in every run; ElevenLabs' only difference is "Flies" heard as "Fly" at one sentence start. Chatterbox renders "flies" as "buies"/"blies" in both styles.

## 2. Where each difference originates

| Difference | Origin |
|---|---|
| Abrupt endings/starts (1, 2) | **Model.** Present in the raw float output before any processing. |
| App missing them (3) | **App** (detection only). |
| Dull 4–10 kHz, 12 kHz ceiling (4) | **Model.** Both engines render the voice duller than the clip they clone, and run at 24 kHz. |
| Faster pace (5) | **Your settings.** Qwen3 *Natural* is 3.14 words/s and 44.5 s total vs ElevenLabs' 3.10 and 43.1 s; Energetic Explainer is 3.68. ElevenLabs sounds energetic without being faster than Natural. |
| Uneven gaps (5) | **Mostly settings and structure:** one generation per paragraph plus your `[pause:n]` marks, so gaps range 0.2–0.7 s. Generating the whole script in one pass gives 0.33 s (SD 0.10), the same mean as ElevenLabs. |
| Narrow pitch range (6) | **Model**, partly reference-dependent (§4). Energetic did not widen it. |
| Digital silence (7) | **App design** (exact zeros are inserted). Perceptual relevance unknown. |
| Seed variance (8) | **Model.** |
| Processing (gain, tempo, loudness, assembly, MP3) | **No audible defect reproduced.** Stages are transparent to within the tolerances above. |

## 3. What was repaired

Only what could be verified as a defect.

* **`voice_studio/audio.py`: `boundary_check` now also reports `tail_decay_db`, `head_rise_db`, `tail_abrupt`, `head_abrupt`** (thresholds −15 dB / −6 dB, calibrated on ElevenLabs and 133 takes). These are diagnostics: nothing is trimmed, faded or retried because of them, existing keys are unchanged, and the "no fades, no edits to generated samples" contract from the previous pass stands. Four new tests; **151 tests pass**.
* **Opening take for the comparison.** Under a rule fixed in advance — lowest seed whose recognised words match the script exactly and whose ending and start are not abrupt — seed 2007 replaced your section-1 take (1996). From section 2 on, the repaired narration is **sample-for-sample identical** to yours (max difference 0.0). Exports: `audio/exports/vs-repaired.{mp3,wav}`.
* **Not repaired**, deliberately: a conditional edge ramp (the previous pass's tests forbid edits to generated samples, and in this narration there are no audible-level edges to ramp — the experiment ramped 0); an automatic retry on abrupt endings (extra generation time of roughly 13 % for Qwen3 and 24 % for Chatterbox; your decision); EQ; noise reduction; stretching.
* Nothing in `local_data/` (voices, sessions, takes, drafts) was modified; a hash manifest taken before testing is compared at the end.

## 4. Naturalness — what the controlled tests show

Hal, nine matching phrases, fixed seeds, one take per input, no take selection (`index.html` has them all; `data/benchmark.json` has every number). Generation is bit-deterministic for a given seed, text and reference, so these are controlled comparisons.

| Source | Length s | Words/s | Pitch range st | Sentence gap s (SD) | Abrupt endings |
|---|---:|---:|---:|---:|---:|
| **ElevenLabs** | 43.1 | 3.10 | 18.8 | 0.33 (0.06) | 0/9 |
| Voice Studio original (Energetic) | 38.2 | 3.59 | 16.4 | 0.40 (0.18) | 1/9 |
| Voice Studio repaired | 37.4 | 3.67 | 16.3 | 0.40 (0.19) | 0/9 |
| Qwen3 Natural | 44.5 | 3.14 | 16.1 | 0.56 (0.20) | 1/9 |
| Qwen3 Energetic | 37.3 | 3.68 | 17.1 | 0.42 (0.18) | 0/9 |
| Chatterbox Natural | 47.9 | 3.09 | 18.3 | 0.89 (0.31) | 3/9 |
| Chatterbox Energetic | 43.8 | 3.41 | 17.5 | 0.74 (0.26) | 1/9 |
| Qwen3 whole script, one pass | 38.9 | 3.49 | 17.4 | 0.33 (0.10) | 2/9 |
| Qwen3 one sentence per take | 44.7 | 3.15 | 16.7 | 0.58 (0.16) | 0/9 |
| Qwen3, reference = Hal's opening question | 43.8 | 3.13 | 18.5 | 0.52 (0.12) | 1/9 |
| Qwen3, reference = all 24 s | 42.2 | 3.37 | 16.0 | 0.59 (0.21) | 2/9 |

What this supports, and what it does not:

* **Energetic Explainer makes speech faster, not more expressive.** Qwen3 Natural → Energetic: +17 % speed, +1.0 st pitch range (inside the phrase-to-phrase SD of 2.4–2.8 st), a slightly narrower loudness range (19.0 → 17.4 dB). Chatterbox: +10 % speed, pitch range *narrower* (18.3 → 17.5). This matches your fifth observation. The speed is also faster than ElevenLabs' own pace.
* **Text splitting affects rhythm, not pitch.** One pass gives ElevenLabs-like gaps (0.33 s) and the lowest pace variation, but two phrase endings are abrupt and there is no per-section control, so editing a single sentence regenerates everything. Per-sentence generation gave no gain in pitch range. Gap size elsewhere is set by the style and your pause marks.
* **Reference window: not a reliable lever (corrected 23 October).** An earlier version of this report said cloning from Hal's opening question "moved Qwen3's mean pitch to ElevenLabs' value". That came from one seed per section and was **seed noise**. Re-tested with five seeds per cell (45 takes, `docs/NATURAL-NARRATION-UPGRADE.md`), a question-style reference did not raise pitch or widen pitch range on a question (+1.4 Hz, d = 0.12) and the effects change sign between sentence types. Only a small speed-up recurs (+0.15 to +0.21 words/s).
* **Key-word emphasis: inconclusive.** F0 and level on eleven key words had SDs of 2.4–6 st; no reliable difference between sources.
* **Intonation at endings: not compared quantitatively.** End-of-phrase pitch movement measured with a simple tracker and approximate word times was too unstable to report.
* **Voice consistency** (spread of per-phrase mean pitch): 1.1 st for both ElevenLabs and Voice Studio; Chatterbox Natural 2.1 st. Chatterbox's mean pitch (162–171 Hz) is also lower than ElevenLabs' (186 Hz).
* **Not established:** that any of these numbers corresponds to sounding natural, or that an "ElevenLabs-like" measurement means an ElevenLabs-like voice.

## 5. Listening files

`samples/elevenlabs-benchmark/index.html` — works offline by double-click; level-matched to −24 LUFS; blind mode shuffles and hides names. Fourteen sources, nine phrases each, plus whole narrations:

* ElevenLabs reference; your original; the **raw engine output** of the same takes; the **repaired** narration.
* **Two experiments, not part of the app:** a −82 dBFS room-tone floor in the digital-silence gaps (tests item 7); a +4.5 dB shelf above 3 kHz (the measured gap in item 4).
* Qwen3 and Chatterbox, Natural and Energetic.
* Qwen3 whole-script, per-sentence, opening-question reference, 24 s reference.

Suggested order: blind-listen to phrase 1 (opening question) — original vs repaired vs ElevenLabs, using "last second"; then phrase 3 (pace); then the presence experiment on any phrase; then the room-tone experiment through your usual headphones.

## 6. Verification

All suites ran against **cloned data** under `samples/elevenlabs-benchmark/verification/` (logs and JSON are there), never against `local_data/`, and with the earlier pass's evidence files left in place. Network access was denied to the engine runs.

| Check | Result |
|---|---|
| Unit tests (`pytest`) | **151 passed** (previously 147 with the four new edge-diagnostic tests; no skips) |
| Isolated Qt widget checks (`final_quality_gui.py`) | **9/9** — Hal is the default voice; VDL timing marks reuse selected takes; section edits keep standalone pauses; malformed directions are blocked; Handbook search; legacy/unchecked labels; controls fit at both window sizes |
| Desktop/media check (`gui_check.py`) | **34 results, none false** — default voice Hal, two voices (Hal, Mike), both engines offered (Qwen3 default), engine choice persists, take switching without regeneration, project/draft restore, playback. It plays real audio through your output device briefly. |
| Real worker integration (Qwen3 → Chatterbox replacement → retime → resume → WAV/MP3 export) | **All 7 assertions true.** Qwen3 20.3 s, peak MLX 3.62 GB, resident 0.54 GB; Chatterbox 87.3 s, peak 4.43 GB, resident 0.80 GB; retiming 0.32 s and resume 0.14 s with no model load |
| Hybrid check (`hybrid_check.py`, mixed engines, manual take selection, stale detection, both exports) | **0 failures**, peak 4.72 GB |
| Your library | `local_data/` hash manifest taken before and after: **every file identical**. Both Downloads MP3s match their original SHA-256. |

Reading these correctly: they show that the app still works and that nothing was damaged. They say nothing about whether the audio sounds better — that is what the listening page is for. Mike remains available (`voice_count` 2, Mike present in the library). Memory peaks stay under 5 GB with one engine loaded, which is workable on an 8 GB M1 but leaves little room for other heavy apps while a Chatterbox take is generating.


## 7. Can Voice Studio approach ElevenLabs' naturalness without replacing its engines?

Partly, and the realistic gains are smaller than the gap.

**Within reach** (settings, workflow, small code): use Natural pacing instead of Energetic Explainer (matches ElevenLabs' speed and total length); treat truncated endings as a reason to re-roll a take (the diagnostic exists; retry is one decision away); choose between whole-script and per-section generation as a rhythm-versus-control trade. A gentle presence lift and a room-tone floor are testable by you right now; I would only adopt them if you hear the benefit.

**Not within reach with these engines:** 4–10 kHz detail the models never render (the 24 kHz ceiling and a 4–8 dB deficit even against their own reference), ElevenLabs' sentence-aware prosody from a commercial-scale model (a 0.6 B 8-bit open model copies a short reference and rolls dice per take), and consistent take quality without trying several seeds. Statistical closeness cannot demonstrate that a listener will hear a voice as equally natural.

**Cost:** each extra attempt is about 1.3× real time with Qwen3 (≈ 10× with Chatterbox), peak memory 3.9–4.0 GB, resident ≈ 0.6 GB — workable on an 8 GB M1 with one engine loaded.

**Decisions for you after listening:** (a) retry automatically on abrupt endings? (b) Natural as the default style? (c) adopt either experiment? (d) nothing further on the reference window, which proved not to steer delivery? I had made none of these changes.
