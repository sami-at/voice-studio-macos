# Voice Studio — test results

Measured on the target machine, not estimated. Re-run any section with the script named beside it.

| | |
| --- | --- |
| Machine | Apple M1 MacBook Air, 8 GB unified memory |
| macOS | 26.6.2 (arm64) |
| Python | 3.11.17, project `.venv` (`include-system-site-packages = false`) |
| Models | Qwen3-TTS 12 Hz 0.6B Base 8-bit MLX · Whisper Base MLX, pinned in `models.lock.json` |
| Date | 19 October 2026 |

Full environment, including package versions and the Metal device report, is in `docs/environment.json`.

## Summary

| Area | Result |
| --- | --- |
| Unit tests (`pytest`) | 19 passed |
| Real voice generation | Works. 42.5 s narration from a 3-paragraph script |
| Apple Metal GPU | Confirmed in use (`Apple Metal (MLX)`) |
| Fully offline generation | Confirmed inside a network-denied sandbox |
| Desktop workflow | All steps pass (`scripts/gui_check.py`) |
| WAV / MP3 export | Both valid and playable |
| Finder launch | `Voice Studio.app` opens and runs from the project folder |

## Speech generation (`scripts/inference_check.py`)

Reference voice: the public-domain LJ Speech clip in `samples/`, 8.3 s, labelled
**Demo · LJ Speech (public domain)**. This is a demonstration voice, not the owner's voice.

| Measure | Value |
| --- | --- |
| Script | 3 paragraphs, split into 3 sections |
| Narration produced | 42.53 s |
| First pass, 3 sections | 47.5 s total (13.5 s, 16.4 s, 17.6 s) |
| Speed | Roughly 1.1× real time once the model is warm |
| MLX peak memory | 3.835 GB |
| Whole check, end to end | 87.9 s (two model loads, regeneration, two exports, two transcriptions) |

**First run is much slower.** The very first generation on this machine took 161 s for the same
script because Metal shaders compile on first use. That cache persists, so later runs are the
numbers above. Expect the first generation after installation to take two to three times longer.

### Is the speech actually correct?

The generated narration was transcribed back with the local Whisper model and compared with the
script. Every sentence came back, with a single word misheard (`leave` → `leap`) — which is as
likely to be a transcription error as a synthesis one. The output is intelligible, correctly
paced, connected speech, not noise.

The reference clip itself transcribes as `...devoid of an elementary cavity`, where the true
line is `alimentary`. This is a limitation of the small Whisper model, and it is exactly why the
app asks you to read and correct the reference transcript before generating.

### Section regeneration

Regenerating section 2 alone replaced only that file; sections 1 and 3 kept their original audio
(asserted in the check). Editing or re-taking one section never discards the rest.

## Offline operation (`scripts/offline_check.py`)

The worker runs inside `sandbox-exec` with `(deny network*)`. The check first proves the sandbox
works by confirming an outbound socket to `1.1.1.1:443` fails, then generates speech inside it.

| Measure | Value |
| --- | --- |
| Sandbox blocks network | Yes (verified before the run) |
| Generation | Succeeded, 4.7 s of audio |
| Device | `Apple Metal (MLX)` |
| MLX peak memory | 3.805 GB |

No network access is needed to generate speech. The worker additionally forces Hugging Face and
Transformers into offline mode and points their caches inside `local_data`.

## Memory on 8 GB (`docs/environment.json`, worker `metrics` events)

The model itself is modest; the transient cost of decoding audio was the problem.

| Phase | MLX memory |
| --- | --- |
| After loading the model | 2.06 GB |
| Peak during generation, before optimization | 5.38 – 5.91 GB |
| Peak during generation, after optimization | **3.64 – 3.84 GB** |

This M1 reports a Metal `max_recommended_working_set_size` of **5.73 GB**. The original one-shot
decode peaked *above* that ceiling; generation now stays comfortably under it.

**The fix.** The codec used to decode a whole section in one pass. It now decodes in ~2 s chunks
(`stream=True`, `streaming_interval=2.0` in `voice_studio/worker.py`). Verified side by side on
identical text and seed: peak fell 5.38 → 3.84 GB, generation got *faster* (12.2 s → 9.7 s), the
two waveforms match at 0.993 cosine similarity, and both transcribe to the identical sentence.
Quality is unchanged.

**Honest caveat.** 8 GB is still tight. Measured on this Mac with its normal apps open, the
system was already swapping about 1.75 GB per 25 s *while completely idle*. A generation adds
meaningfully to that, and a cold run under pressure took 66 s against 28 s for the same text once
warm. The app's design limits the damage — synthesis runs in a separate process that exits and
returns all of its memory after each task — but **close memory-heavy apps before a long
narration**. Swapping costs speed, not correctness: no run was ever killed or produced bad audio.

## Desktop application (`scripts/gui_check.py`)

Drives the real Qt widgets, the real audio device, and a real inference process.

| Step | Result |
| --- | --- |
| Window launches and shows | pass |
| TXT import, title from filename | pass |
| Waveform renders | pass |
| Playback, pause, seek | pass |
| Reference preview, section preview | pass |
| Switch preview while paused after a seek | pass (see below) |
| UI responsive during generation | pass — 287 timer ticks while the worker ran |
| Cancel during generation | pass — 0.31 s |
| Cancel preserves finished sections | pass |
| Profiles and draft survive a restart | pass |
| Audio output devices found | 2 |

### A freeze that was found and fixed

Pausing playback, dragging the timeline, then switching to another preview **hung the whole
application permanently**. The cause was `QMediaPlayer.stop()` in Qt 6.8's FFmpeg backend: from
that state it makes a blocking cross-thread call that never returns. Reduced to a minimal
reproduction:

| Sequence | Result |
| --- | --- |
| pause → seek → `stop()` | deadlock |
| pause → `stop()` | fine |
| play → `stop()` | fine |
| pause → seek → `setSource()` | fine |

`setSource()` already stops and resets playback, so all three `stop()` calls were removed. The
workflow check now covers this sequence, and a watchdog aborts the check with stack traces
instead of hanging if anything similar reappears.

This path is exactly what the README recommends — play the result, seek, compare with the
reference — so it would have been hit in ordinary use.

## Export

| Format | Result |
| --- | --- |
| 24-bit WAV | 42.53 s, 24 kHz mono, `pcm_s24le` |
| 320 kbps MP3 | 42.58 s, 48 kHz mono |

Both written to `samples/generated-demo.*` and verified with ffprobe. Exports are normalized
(`loudnorm=I=-18:TP=-1.5:LRA=11`) and written to a temporary file that is renamed into place, so
a failed or cancelled export cannot truncate an existing file. The same applies to generated
sections, assembled narrations, and every JSON file the app saves.

## Finder launch

`Voice Studio.app` launches through LaunchServices, runs from the project folder, and uses the
project's `.venv`. It holds a single-instance lock: opening it twice shows "Voice Studio is
already open" rather than starting a second copy.

The launcher previously redirected its output to a log file *before* checking that the Python
environment existed, so a missing or moved `.venv` produced an app icon that bounced and died
silently. It now checks the project folder and interpreter first and reports failures in a native
dialog; `app.py` does the same if the desktop components fail to import.

## Narration styles and delivery controls (`scripts/style_check.py`)

Before building any control, each knob the engine exposes was tested on identical text,
**three seeds per setting**, and compared against the seed-to-seed spread at a fixed setting.
This matters: a single take per setting suggested `top_p` widened pitch range, and three takes
showed that was noise.

### What the model does not give you

| Knob | Measured result |
| --- | --- |
| `temperature` 0.3 - 1.1 | No systematic effect. Rate 2.93-3.06 words/s with no trend; pitch spread 4.73-5.36 semitones with no trend. |
| `top_p` 0.8 / 0.9 / 1.0 | Mean pitch spread 4.83 / 5.02 / 4.93 semitones. Within-setting spread (4.54-5.49) exceeds the differences between settings. No effect. |
| `repetition_penalty` 1.05 vs 2.0 | Byte-identical output. The cloning path raises anything below 1.5 to 1.5. |
| `top_k` 20 vs 50 | Changes the take, not the style. |
| model `speed=` argument | **Never reaches the model.** Not forwarded on the reference-cloning path. |
| `instruct=` style prompt | Rejected by the base checkpoint; it is for the VoiceDesign variant. |

So sampling settings choose *which take* you get, not how it is delivered. They are fixed at the
validated values and deliberately not offered as style controls.

### What does work

Conditioning on a **tempo-shifted copy of the reference recording** genuinely steers delivery,
because reference cloning copies the sample's pacing. Measured, three seeds each:

| Reference | Words per second |
| --- | --- |
| slowed to 0.88x | 3.04 (2.86, 3.15, 3.10) |
| as recorded | 3.05 (3.12, 2.95, 3.08) |
| sped to 1.15x | **3.37** (3.33, 3.22, 3.56) |

Every fast-reference take beat every other take, and all three transcribed back perfectly. Note
the asymmetry: **speeding the reference up works, slowing it down does nothing.** Slower styles
therefore get their pace from the post-generation stretch, which is exact. The words in the
reference are untouched, so the saved transcript stays valid.

### The four controls, and what each is

| Control | Mechanism | Reliable? |
| --- | --- | --- |
| **Reference pace** | Stretches the sample the model listens to | Yes, upward. Downward has no effect |
| **Final speed** | Pitch-preserving stretch after generation | Yes, exact and deterministic |
| **Paragraph pause** | Silence inserted between paragraphs | Yes, exact |
| **Section pause** | Silence between sections inside a paragraph | Yes, exact |

### Styles compared on the same script

Same 61-word script, same demonstration voice, via the real worker:

| Style | Length | Words/sec | Longest pause | Words recovered | Peak memory |
| --- | --- | --- | --- | --- | --- |
| Documentary | 23.92 s | 2.55 | 1.43 s | 98% | 3.835 GB |
| Natural | 22.33 s | 2.73 | 1.18 s | 98% | 3.835 GB |
| **Energetic Explainer** | **17.65 s** | **3.46** | 0.48 s | 98% | 3.834 GB |

Energetic Explainer is **26.7% faster** than Natural and 4.7 s shorter on this script, with the
longest pause cut from 1.18 s to 0.48 s — and identical intelligibility. The 2% not recovered is
the same spelled-out number in every style, not a style defect. Peak memory is unchanged, so the
8 GB optimization still holds.

### Requested controls that are not offered

These were asked for, investigated, and deliberately **not** built, because nothing in this
engine delivers them honestly:

- **Expressiveness / pitch variation.** No parameter moves pitch range outside seed noise (see
  the table above). Faking it with a pitch-shifting filter would change the speaker's identity
  and sound processed, which is the opposite of the brief.
- **Emphasis on particular words.** The base model takes no emphasis markup, and the cloning
  path takes no style prompt. Word-level loudness boosting would need forced alignment and
  sounds artificial. Rewriting the sentence, or regenerating the section for a different take,
  is the honest route.
- **Narration consistency as a dial.** Consistency comes from the fixed per-section seed already
  in use, not from a sampling setting: at temperature 0.3 three takes varied 11.12-11.44 s, and
  at 0.9 they varied 10.32-10.96 s. Lower temperature was not more consistent.

## Imported voices (`scripts/import_voice_assets.py`, `scripts/voice_check.py`)

Two user-supplied recordings were imported as **Mike** and **Hal**. The reference window is
chosen from the local Whisper model's own word timings rather than from raw signal energy, so
a reference always begins and ends on a complete word, and a sentence boundary is preferred.
Candidate windows are scored on transcription confidence, speech density, closeness to twelve
seconds, and absence of long internal pauses.

| Voice | Window picked | Length | Confidence | Speech density | Longest internal gap |
| --- | --- | --- | --- | --- | --- |
| Mike | 10.90 - 23.24 s | 12.34 s | 0.990 | 0.912 | 0.46 s |
| Hal | 11.00 - 24.06 s | 13.06 s | 0.993 | 0.917 | 0.44 s |

Both windows end on a full stop. Each transcript was produced twice — once from the whole
recording and once from the trimmed reference the model will actually be conditioned on — and
the two readings agreed **exactly** (1.000) for both voices. Source files were SHA-256 checked
before and after import and are unmodified; the importer copies, never writes back.

### Do the generated voices actually clone their own reference?

Sounding *different* is not enough, so each result was matched back against both references
using a long-term average spectrum of the voiced frames, and against the references' pitch.

| | Reference pitch | Generated pitch | Error |
| --- | --- | --- | --- |
| Mike | 131.1 Hz | 133.3 Hz | +1.7% |
| Hal | 154.8 Hz | 165.0 Hz | +6.6% |

| Generated | Similarity to Mike's reference | Similarity to Hal's reference | Closest |
| --- | --- | --- | --- |
| Mike | **0.9866** | 0.8248 | Mike |
| Hal | 0.9305 | **0.9390** | Hal |

Every voice matched its own reference, and the two results are 31.7 Hz apart in median pitch —
about 3.7 semitones, plainly audible. Both transcribed back to the script word for word, and
both ran at the usual 3.84 GB peak. Generating never altered a stored profile
(`profile_unchanged_by_generation` is true for both).

**One honest caveat.** Mike's margin is decisive (0.987 against 0.825); Hal's is thin
(0.939 against 0.931) on the spectral measure alone, and the two *generated* voices resemble
each other (0.927) more than the two *original* recordings do (0.841). The cloning pulls both
voices somewhat toward the model's own timbre. Pitch separates them clearly and they are not
confusable by ear, but do not expect a 0.6B model to reproduce a professionally cloned voice
exactly.

### Licensing

Both recordings are ElevenLabs output, and the filenames carry the `pvc` (professional voice
clone) marker. Each profile stores its source filename, full path, SHA-256, and an
`authorization` note recording that **the licence has not been verified** and that ElevenLabs'
terms may restrict re-cloning, redistribution, and commercial use. Voice Studio does not and
cannot check this. Confirm your rights before publishing anything made with these two voices.

## Incomplete narrations: cause and fix

### What was actually wrong

A section's audio was tied to its text by **nothing but a file path**. `segment['file']`
recorded where a recording lived; no field recorded *which words it was made from*. Assembly
only checked that the files existed. So if a section's wording and its recording ever came
apart, the app would assemble, play and export the old audio as though it were correct.

One saved narration on this machine was in exactly that state. Section 1 read
`"hi how are you you good"` — six words — while its recording was 14.16 s of
`"Welcome to Voice Studio. This narration was created locally on this Mac..."`. The section
had been edited in the app, which correctly cleared its audio, and a later repair re-attached
the previous recording by path without checking the words. Nothing in the pipeline objected.
That is the reported symptom: a narration whose beginning does not match the script.

### What was ruled out, and how

Before changing anything, each stage was measured rather than assumed:

| Suspected stage | Evidence |
| --- | --- |
| Streaming codec decode | Same text and seed, streaming vs one-shot: identical durations and identical transcripts on 3 scripts. Not the cause. |
| Silence trimming, loudness, speed stretch | 64 generations transcribed **before and after** processing. Words lost by our processing: **0**. Head wrong: 0. Tail wrong: 0. |
| Long sections near the split limit | 20 further generations at ~200 characters. Coverage 1.0 on 19, 0.972 on one. Head wrong: 0. Tail wrong: 0. |
| Assembly, resume, regeneration, export | Covered end to end below; all complete. |

Across **84 single-section generations**, our processing never removed a word and never lost a
first or last word. The pipeline does not truncate.

### The fix

Each generated section is now stamped with a fingerprint of the exact words it was made from:

- A section whose text no longer matches its fingerprint is **stale**, and both the worker and
  the Sections table treat it as pending, so Generate re-records it.
- Assembly **refuses** to join stale audio and says which section was edited, instead of
  producing a narration that does not match the script.
- `scripts/repair_sessions.py` listens back to narrations made before fingerprints existed and
  stamps each section that matches its text. Of 59 existing sections, 58 were stamped and
  **1 was detached** — the damaged one. No audio file is ever deleted, only unlinked.

### Completeness verification and bounded retries

A 0.6B zero-shot model does occasionally drop or garble a word, so every section is now listened
back to and compared with the script before it is accepted. A section that does not match is
retried with a different seed, up to three takes; the best take is kept and the rejected ones
are removed.

Speech recognition is imperfect, so the comparison is built to ignore differences that are not
missing audio: contractions are expanded both ways (`there's` / `there is`), transcriber
spellings are folded (`blink's` / `blinks`), digits are spelled out, and punctuation and case are
dropped. **Calibrated against all 84 measured generations, it raises zero false alarms**, with the
tightest passing margin at 0.976.

Edge checks use alignment position rather than word membership — a dropped `"the day"` would
otherwise look present because some other `the` survives elsewhere in the sentence:

| Case | Verdict |
| --- | --- |
| Real transcriber quirks (contraction, misspelling, mis-heard first word) | passes |
| 1 word lost at either end | passes (within ASR slack) |
| 2 words lost at the start | **detected** |
| 2 words lost at the end | **detected** |
| 5 words lost at the end | **detected** |
| A clause dropped from the middle | **detected** |
| Half the sentence, or silence | **detected** |

A section that still fails after three takes keeps its closest take, is recorded as
`verified: false`, and is reported to you by name in a dialog. It is never silently accepted.

The retry path was exercised by stubbing the verifier, since real generations pass:

| Scenario | Takes made | Take kept | Marked verified | Reported |
| --- | --- | --- | --- | --- |
| Fails once, then passes | 2 | 2 | true | no |
| Never passes (0.40, 0.70, 0.55) | 3 (bounded) | 2 (the best) | false | yes |

Forcing that path found a real crash in the new code — the summary read an `ok` key that the
stored check did not carry — which would have broken generation precisely when a section failed.
Fixed, with a regression test.

### End to end, on real audio (`scripts/completeness_check.py`)

Every section, every assembled narration and both exports are transcribed back and compared
with the script. Nothing here is taken on trust from the worker's own verdict.

| Case | Result |
| --- | --- |
| Mike / Natural, 3 paragraphs | complete, coverage 0.990 |
| Mike / Energetic, 3 paragraphs | complete, coverage 0.990 |
| Hal / Natural, 3 paragraphs | complete, coverage 0.980 |
| Hal / Energetic, 3 paragraphs | complete, coverage 0.990 |
| Mike and Hal, two-word script | complete, coverage 1.000 |
| Sections opening and closing on short words | complete |
| Partial run, then resume | complete; the finished section was not re-recorded |
| Regenerate one section | complete; neighbouring sections untouched |
| WAV export / MP3 export | complete, coverage 0.990 |

**0 failures.** Peak memory **3.99 GB**, against 3.84 GB before verification was added — the
listening-back costs about 0.16 GB, and still sits well under this M1's 5.73 GB working set.

## Naturalness: what the engine can and cannot do

Every claim below was measured before anything was changed.

### Expressiveness is not available from this model

| Avenue | Measured result |
| --- | --- |
| temperature, top_p, top_k, repetition_penalty | No effect on pace, pitch range or loudness beyond seed noise (see the styles section). |
| `instruct=` emotional prompt | Rejected by the base checkpoint. |
| Punctuation steering intonation | `?` versus `.`, same words, 5 seeds, 2 voices: Hal's questions end **1.5-1.8 semitones lower** than its statements, Mike's end **2.5-3.0 higher**. Opposite signs between voices, and within one condition takes ranged from -9.9 to +12.0 semitones. No usable effect. |
| An expressive reference window | A reference 0.45 semitones *more* varied in pitch produced output 0.49 semitones *less* varied. Inverted, so no transfer. |
| Reference tempo | **Works** — the one genuine lever, already used by the styles (3.05 → 3.37 words/s). |

So context-aware prosody, emphasis on chosen words, and emotional delivery are **not
implementable** on this engine. They were not built, and no control was added that pretends
otherwise. A convincing slider that moves nothing would be worse than its absence.

### Sentence endings are generated and kept complete

The suspicion was that silence trimming ate the final consonant or the vocal decay. It does not.
Across 16 generations (2 voices, 8 endings: *over, world, different, understand, pass, life,
away, back*):

- trimming removed **0 ms** of audio from the tail in 14 of 16 cases;
- in the other 2 it removed 10-20 ms measured at **-78 dB and -92 dB** below peak, which is
  digital silence, not speech;
- 0-120 ms of natural decay sits past the detection threshold in these clips, and all of it is
  kept by the 100 ms padding.

**No fix was needed here, so none was invented.** Nothing stretches a final phoneme, shifts
pitch, or adds a synthetic breath.

### What was actually wrong: the joins, and the ending

Three measurable faults, all in timing rather than in the speech:

1. **Pauses were not the length they claimed.** Each section carried up to 100 ms of padded
   silence at *each* edge, which was added on top of every pause. One measured narration asked
   for 0.30 s between paragraphs and got **400-500 ms**. The amount varied with however much
   silence the model happened to leave, so the setting drifted unpredictably.
2. **Every join was the same length.** A section cut mid-sentence at a comma was given the same
   gap as a section ending in a full stop, which is what made long paragraphs sound disconnected.
3. **A narration stopped dead.** Silence was inserted *between* sections only, so the file ended
   **60 ms** after the last word — the abrupt ending.

### The change

Assembly now removes each section's dead padding while keeping its natural decay (60 ms after a
sentence, 25 ms mid-phrase), then inserts exactly the gap the style asks for. The gap depends on
how the section ends — paragraph, sentence, clause, or mid-sentence — and the narration opens
with a short lead-in and closes with room to finish.

Measured on identical speech (the same generated sections assembled both ways, so the only
difference is the phrasing):

| | Before | After |
| --- | --- | --- |
| Room after the last word | 63-97 ms | **380 ms** in all four cases |
| Lead-in (Mike/Natural) | 1 ms | **81 ms** |
| Clause join, Energetic | 215 ms | **81 ms** (the configured value) |
| Clause join, Natural | 147 ms | **126 ms** (the configured value) |
| Every other gap | unchanged, sample for sample | unchanged |

That last row matters: the model's own pauses inside a section are untouched. Only the joins
moved. Pause defaults were raised to match, since the old numbers were landing up to 200 ms
longer than they claimed.

**Honest limits of this change.** When a script's paragraphs each fit in one section — the common
case for short videos — there are only paragraph joins, and the phrasing difference is small; the
audible win is the ending. The tighter clause and mid-sentence joins only matter in paragraphs
long enough to be split, which is where the disconnected feeling came from.

Before-and-after files for listening are in `samples/comparison/`, as WAV and MP3, for Mike and
Hal in both styles plus a long-paragraph case.

### Unchanged by this work

65 unit tests pass. Real-audio completeness: 11 of 11 cases, 0 failures, both voices, both
styles, resume, regeneration and both exports. Retry bounds behave. Peak memory **3.99 GB**,
identical to before.

## Known limitations

- **Not a standalone bundle.** The `.app` is a small native launcher. It needs the project folder
  with its `.venv` and `models` in place. Moving the project means re-running the installer.
- **Ad-hoc signed, not notarized.** Gatekeeper may warn on a machine other than this one.
- **8 GB is the real constraint.** See the memory section. Long narrations want a quiet machine.
- **No Arabic or Darija.** The selected model covers English, French, Spanish, German, Italian,
  Portuguese, Chinese, Japanese, Korean and Russian only.
- **Zero-shot cloning, not training.** Similarity depends on the reference recording. Speech can
  still mispronounce, omit or repeat a word; listen before publishing and regenerate a section.
- **Prosody does not carry across sections.** Sections are generated independently and joined
  with short pauses, so intonation can reset between them.
- **Speed control is post-processing.** 0.75–1.25× is an FFmpeg pitch-preserving stretch, not an
  instruction to the model.
- **Reference transcription can be wrong.** The small Whisper model misheard one word in the demo
  clip. Always check the transcript before generating.
- **Timings are warm-cache.** The first generation after installation is considerably slower.
- **A style changes pace and pauses, not tone of voice.** The character of the delivery comes
  from the reference recording. An energetic narration needs an energetic sample; no setting
  turns a calm recording into an excited performer.
- **No emotional or emphasis control.** Measured: nothing this engine exposes moves pitch range,
  loudness or emphasis beyond seed noise, so the narration reads the meaning only as far as the
  words themselves carry it. Expressive delivery has to come from the reference recording.
- **Phrasing control is timing, not intonation.** Styles change pace and the length of joins. A
  question will not be read with a rising inflection because the script has a question mark.
- **Explainer Narrator is a delivery style, not a person.** It ships pointing at the
  public-domain sample and is not an imitation of any particular narrator. Point it at a
  recording you own, or have written permission to use, to give it a different voice.
