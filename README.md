# Voice Studio

A local macOS desktop studio for turning TXT scripts into narration using a recording of your own voice. Voice profiles, transcripts, projects, and generated audio stay on this Mac. There is no account, API key, subscription, cloud speech service, or local web server.

This installation is tested and working on this Mac. Measured speed, memory, and the
limitations that remain are in **`docs/TEST_RESULTS.md`**.

## Open the app

Build the launcher once with `.venv/bin/python scripts/build_app.py`, then double-click **Voice Studio.app** in this folder. It is meant to stay here, beside the project
files it uses; a Finder alias or a Dock item is the way to reach it from elsewhere. Finished
narrations are already in the sidebar, so you can
press play and hear it immediately: **Flies explainer · Mike** and **Flies explainer · Hal**
are the same script in both voices. **Launch Voice Studio.command** is the fallback launcher.

The app is a small native launcher that uses this folder's `.venv`, source code, and `models`. Keep the project folder in its current location. It is not a portable standalone bundle. If you move the project, run **Install Voice Studio.command** to rebuild the launcher (recreate `.venv` if Python reports an old path). The launcher is locally ad-hoc signed, not Apple-notarized.

## Your first voiceover

1. Click **Add your voice**, then choose your MP3, WAV, M4A, or FLAC recording.
2. Name the voice. Select a clean **5–15 second** passage using the start time and window length. The default window is the first 12 seconds. End on a complete word or sentence; use a single speaker with no music or strong room echo.
3. Leave **Transcribe the selected sample offline** enabled, then click **Prepare voice**. The original recording is preserved. Preparation converts only the chosen window to mono 24 kHz, trims quiet edges, and adjusts volume.
4. In **Voice reference**, play the prepared sample and correct its transcript to exactly match the audible words. Click **Save transcript**. A transcript of the entire original recording will be wrong if you selected a shorter window.
5. Import your TXT file, or type/paste into **Script**. Name the narration, choose its language, and pick a **narration style** — **Natural** keeps the model's own timing, **Energetic Explainer** is the fast, clear delivery for short videos. See *Voices and narration styles* below.
6. Click **Generate narration**. Expect roughly **1.1x real time** once the model is warm, so about 45 seconds of work for a 45-second narration. The **first** generation after installation takes two to three times longer because Metal shaders compile on first use. The window remains usable and **Cancel** stops the worker within a second. Completed sections are saved automatically; Generate resumes missing sections.
7. Play the result, seek with the waveform or timeline, and use **Voice reference** to compare. In **Sections**, select and preview a passage, edit its words, or **Regenerate section** for a new take. Edits to an individual section leave other generated audio intact.
8. Click **Export audio…** and choose a destination and either **320 kbps MP3** or **24-bit WAV**. Exports receive final loudness normalization and peak headroom.

Voice Studio listens back to every section it generates and compares it with your script. A
section that does not match is re-recorded automatically, up to three takes. If one still does
not match, the closest take is kept and you are told which section to check — it is never
quietly accepted as finished.

Editing a section's words marks its old recording out of date. Those sections show as
**Pending** and are re-recorded on the next Generate; a narration is never assembled from audio
of different words. If a narration made before this check existed looks wrong, run
`.venv/bin/python scripts/repair_sessions.py` to audit it (add `--apply` to write the repairs;
no audio file is ever deleted).

Saved narrations appear in the sidebar. Double-click one to reopen it. Script drafts also survive a normal restart. Older sample versions and generated takes remain on disk, so replacing a profile does not break an older narration.

## Engine and hardware

This installation targets an **Apple M1 MacBook Air, 8 GB unified memory, macOS 26.6.2**, with roughly 30 GiB free before setup. It uses **Qwen3-TTS 12 Hz 0.6B Base, 8-bit MLX**, with a local **Whisper Base MLX** model for transcription. Python 3.11 and PySide6 provide the desktop app. FFmpeg is included in the project environment through imageio-ffmpeg, so no global FFmpeg install is needed.

The model performs **zero-shot reference-based cloning**. Creating a profile does not train or fine-tune a model. Similarity, accent preservation, pronunciation, and pacing depend on the source and language. Listen before publishing; speech generation can still omit, repeat, or mispronounce words. Section regeneration makes these errors easier to fix.

MLX uses the Apple **Metal GPU**, not the Neural Engine and not PyTorch MPS for synthesis. Inference runs in a separate process and exits after each task to release its memory. The smaller 0.6B model is a practical choice for 8 GB; a larger model could improve quality but competes more heavily with macOS and other apps.

Generation peaks at about **3.8 GB** of MLX memory, under this M1's 5.73 GB Metal working-set limit. The codec decodes in short chunks rather than a whole section at once, which keeps the peak down and is slightly faster. Even so, 8 GB is tight: this Mac was already swapping while idle with ordinary apps open, and synthesis adds to that. **Close memory-heavy apps before a long narration.** Swapping costs speed, not correctness.

## Voices and narration styles

The **Voice Library** holds as many voices as you like, each with its own recordings,
transcript, and default style. Switching between them never touches another voice's files. Two
are set up:

| Voice | State |
| --- | --- |
| **Hal** | Imported from a supplied ElevenLabs recording, 13.1 s reference, Energetic Explainer. Opens selected by default. |
| **Mike** | Imported from a supplied ElevenLabs recording, 12.3 s reference, Energetic Explainer. |

**Both carry a licence warning.** They were imported from ElevenLabs recordings whose filenames
carry the professional-voice-clone marker. Their profiles record the source file, its SHA-256,
and a note that **the licence was not verified** — ElevenLabs' terms may restrict re-cloning,
redistribution, and commercial use. Voice Studio cannot check this for you. Confirm your rights
before publishing anything made with either voice.

Manage voices from the **Voices** menu or by right-clicking the library: add, create an empty
voice, replace a sample, rename, or remove. Removing a voice leaves narrations you already
generated with it untouched — they still open and play, and keep the name of the voice that made
them, but they cannot be regenerated without a voice to regenerate from.

To add your own voice, choose **Voices &rarr; New empty voice…**, then **Replace sample…** with a
clean 5-15 second recording. Or import any recording directly, letting the app pick the cleanest
reference window for you:

```sh
.venv/bin/python scripts/import_voice_assets.py --name "Their Name" \
    --source ~/Downloads/recording.mp3 --style "Energetic Explainer" \
    --note "Who authorised this voice, and how."
```

### Mood clips

A cloned voice copies the delivery of its reference, so one sample gives one mood. A voice can
also carry **mood clips**: short references of the same speaker sounding neutral, excited, sad,
angry, scared, playful, warm, or calm. Each section is generated from the clip that fits its
words. In **Sections**, the **Mood** box shows what *Auto* picked (from plain word cues such
as "thank you", "absolutely not", "shh") and lets you override it. Then press **Generate
section** for a new take. Existing takes are kept, and each one records the mood it used.

Cut clips from one recording of the speaker, either by hand or found from the transcript:

```sh
.venv/bin/python scripts/import_voice_moods.py --name "Mr. Stick" \
    --mood neutral=12.0-24.6 --mood sad=51.3-63.5      # windows in seconds
.venv/bin/python scripts/import_voice_moods.py --name "Mr. Stick" --auto
```

On the same six-line script, mood clips moved the median pitch from 128 Hz (neutral) to
308 Hz (excited), 333 Hz (angry), and 99 Hz (sad). With a single reference, every line stayed
between 119 and 168 Hz.

## Writing directions into a script

A few marks can be typed straight into the script. The **Handbook** button above the script
editor opens a searchable reference with examples you can insert; everything in it was measured
on this Mac, and what does not work is listed as not working. **Copy handbook** puts a plain-language
guide to writing a script, followed by every mark, on the clipboard (or **Save as file…** for a
Markdown copy) so you can send it to someone; **Copy this chapter** copies just the one you are reading.

| Mark | Does | Reliable? |
| --- | --- | --- |
| `[pause:0.6]` | Inserts that duration of digital silence; natural quiet is retained | Exact inserted samples; inline placement requires alignment |
| `{written\|spoken}` | Shows one spelling, speaks another | Yes |
| `word[say:spelling]` | Respells the word just before it | Yes |
| `,` `.` `?` `!` `…` | Lengthens the gap, by an amount you do not control | Varies by engine |
| `[pace:slow]` `[pace:fast]` `[pace:normal]` | Re-times that section by about 7 % (pitch preserved), from its saved raw take as a new take | Yes: exact stretch; speed only, not expression |
| `*word*`, `CAPITALS` | Nothing useful — changes the take like a new seed would | No |
| `[delivery:…]` `[emotion:…]` `[emphasis:…]` | Refused with a reason: no installed engine can honour them while cloning | Not supported |

The **Review** tab compares each join between sections (loudness, typical pitch, brightness, gap), lists
measured warnings on takes, and can play any join. A take whose ending or start stops at near full level
is marked *needs review* and re-recorded with another seed; it is never faded or deleted. Details in
`docs/NATURAL-NARRATION-UPGRADE.md`.

The script you write is never rewritten: markers are stripped before the engine sees the words,
and the completeness check compares the audio against the spoken form rather than the markers.
Changing only timing reuses compatible takes. Changing spoken words marks takes stale without deleting them.
Measurements are in `docs/VOICE-DIRECTION.md`.

## Two engines, your choice per section

Each section can be recorded by either engine, and **you** pick which take goes into the
narration. Nothing chooses for you.

| Engine | Character |
| --- | --- |
| **Qwen3-TTS** (default) | Fast, about 1.4x real time, and well tested. |
| **Chatterbox v3** | A second opinion for a phrase that does not sit right. Slower than Qwen3, about 5x real time. |

Set the engine for the whole narration beside **Narration style** on the Script screen. Any
section can override it: in the **Sections** tab, choose the engine for that section, press **Generate section**, then
**Generate with other engine** to hear the alternative. Both recordings are kept in the
**Takes** list beside the words. Double-click a take, or select it and press **Use this take**,
to put it in the narration — that never regenerates anything. Press **Generate narration** to
reassemble with your choices.

Every take stores the engine, its settings, the exact words it was recorded from, and its
completeness result. Editing a section's words marks its takes **stale** rather than deleting
them: restore the original wording and the take becomes usable again. A narration is never
assembled from stale audio.

Chatterbox keeps the existing `cfg_weight=0.0` configuration. The installed dependency
accepts the streaming options but ignores them; the older claimed streaming speedup is
not established for this installation. Current measured time and memory are reported in
`docs/FINAL-QUALITY-REPORT.md`. Neither engine guarantees identical voice identity.

Only one engine is held in memory at a time. Consecutive sections on the same engine reuse the
loaded model; switching engines frees the previous one first. Peak memory stays around
**3.8 GB** for Qwen and **4.5 GB** for Chatterbox.

**On emotional delivery.** Neither engine takes direction. Eighteen local TTS families were
searched for one that accepts an emotion instruction *and* a cloned voice: the architectures that
do are non-commercially licensed, and the commercially usable one (VoxCPM2) did not change its
delivery when instructed while cloning. The measurements, licences and audio samples are in
`docs/EXPRESSIVE-RESEARCH.md`. Expressive character comes from the reference recording — a
reference of someone sounding curious produces curious narration.

**On Chatterbox's `exaggeration` setting:** it defaults to 0.5 and is stored with each take, but
measurement here could not show it moving delivery in a consistent direction, so it is not
presented as an expressiveness control. Treat it as a per-take variation to try by ear.

Pick a **narration style** above the script:

| Style | Pace against Natural | Character |
| --- | --- | --- |
| Natural | — | The reference recording's own pacing. |
| **Energetic Explainer** | **27% faster** | Quick and clear for short explainers, with tight pauses. |
| Documentary | 7% slower | Measured, with room to let a statement land. |
| Storytelling | 4% slower | Unhurried, with long breaths between paragraphs. |
| Custom | your own | Whatever you set the four controls to. |

Four controls sit under the style, and changing any of them switches the style to **Custom**:

- **Reference pace** stretches the sample the model listens to. Because cloning copies the
  sample's delivery, this makes the model genuinely speak faster *in its own voice*. It only
  works upward; slowing the reference does nothing.
- **Final speed** is an exact pitch-preserving stretch applied after generation.
- **Paragraph pause** and **Section pause** set the silence between parts.

Pauses are placed by how each section ends. A full stop uses the sentence pause target, a comma uses
about half of it, and a mid-sentence boundary uses a shorter target. Natural quiet and decay
are preserved; continuous prosody across independent generations is not guaranteed. A narration opens with a short lead-in and ends with
room to finish rather than stopping on the last sample.

**What is deliberately not here.** Expressiveness, pitch-variation, per-word emphasis and
emotional delivery were investigated and left out. Measured against seed-to-seed variation,
nothing this engine exposes moves pitch range or loudness — including punctuation: question marks
do not produce a rising inflection, and the effect runs in opposite directions for different
voices. A convincing-looking slider that does nothing would be worse than none. The measurements
are in `docs/TEST_RESULTS.md`. A style controls pace and pauses; the *character* of the voice —
how warm, how curious, how energetic — comes from the recording you give it.

Supported narration languages: **English, French, Spanish, German, Italian, Portuguese, Chinese, Japanese, Korean, and Russian**. **Arabic and Darija are not supported by this selected model.** Offline Whisper transcription covers more languages, but that does not extend the speech model's language support.

Speaking speed uses FFmpeg's pitch-preserving time stretch after generation (0.75–1.25×); it is not an instruction to the model. Paragraph pauses are configurable. The app preserves internal pauses and quiet attacks/releases without fading spoken samples or overlapping words between sections. A smooth join cannot guarantee continuous prosody across separately generated sections.

## Local storage

- `.venv/`: isolated Python environment and bundled FFmpeg.
- `.setup-wheels/`: retained, checksum-verified dependency downloads for local repair.
- `models/`: pinned local voice and transcription models, including the speech tokenizer.
- `local_data/voices/`: voice profiles, original files, prepared samples, sample versions, and any tempo-conditioned copies a style needed.
- `local_data/sessions/`: scripts, generation settings, per-section WAVs, and combined narrations.
- `local_data/draft.json`: current editor state.
- `local_data/logs/`: local diagnostic logs; these may include model messages and file paths.
- `samples/`: example text, `flies-mike.wav`/`.mp3` and `flies-hal.wav`/`.mp3` (the same script in both voices), earlier demonstration exports, and `engines/` with the listening comparison recordings.
- `local_data/backups/`: timestamped copies of the voice library, written before it is changed.
- `original/`: the untouched starter source, README, and original requirements.
- `docs/TEST_RESULTS.md`: measured results and remaining limitations.

## Comparing narration engines

`docs/engine-comparison.html` is a local listening page: the same script in both engines, level
matched, with A/B controls. Open it by double-clicking, or rebuild it after adding recordings
with `.venv/bin/python scripts/build_comparison.py`. It works entirely offline. The measured
findings behind it are in `docs/ENGINE-EVALUATION.md`; the engine itself is unchanged.

Back up `local_data` to preserve your voices and narrations. The `VOICE_STUDIO_DATA` environment variable can select another data directory. No automatic cleanup deletes your recordings or generated takes. Audio files can accumulate during long projects.

## Repair or reproduce setup

Double-click **Install Voice Studio.command** while online. It refreshes the virtual environment for your installed Python 3.11, installs the exact dependency lock (using retained wheels when available), downloads the pinned model revisions, verifies large-file SHA-256 checksums, and rebuilds the Finder launcher. It never uploads recordings. Downloads only occur through this explicit installer; the desktop worker forces Hugging Face and Transformers offline mode and disables their telemetry.

For development:

```sh
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir -r requirements.lock.txt
.venv/bin/python scripts/download_models.py
.venv/bin/python scripts/build_app.py
.venv/bin/python app.py
```

Run deterministic tests with `.venv/bin/python -m pytest -q`. See the test report for actual inference and GUI validation. Python 3.14 is deliberately not used, even if it is your default system interpreter.

**If you cannot hear anything**, the usual cause is the output device rather than the app: a
Bluetooth speaker that is switched off still shows as the default output, and macOS keeps
routing to it. Voice Studio now notices this and names the device. Change it in System Settings
&rsaquo; Sound, or play `samples/flies-hal.mp3` in Finder to confirm the files themselves are fine.

If the worker stops unexpectedly, check `local_data/logs`, close memory-heavy apps, and retry. Completed sections are retained. If a recording is rejected as silent or too short, select a different sample window. If transcription makes mistakes, edit the text manually. Imported TXT files must be UTF-8 (with or without BOM) or UTF-16 with a BOM. The importer limits individual files to 5 MB.

## Model selection and licenses

The selection is a hardware-informed engineering choice, not a claim of a measured quality win against every alternative. Only the selected model is installed and benchmarked here.

| Candidate | Assessment for this Mac |
| --- | --- |
| [Qwen3-TTS 0.6B Base](https://github.com/QwenLM/Qwen3-TTS) | Selected for compact reference-based cloning, ten languages, Apache-2.0 weights, and an actively maintained MLX implementation. 8-bit quantization keeps a useful quality/memory balance. |
| [F5-TTS](https://github.com/SWivid/F5-TTS) | Good reference-conditioned flow-matching option with Apple Silicon implementations, but the standard pretrained weights are CC-BY-NC. The starter had no reusable profiles, tested local installation, or packaging. |
| [Chatterbox](https://github.com/resemble-ai/chatterbox) | An actively maintained MIT-licensed alternative with expressive cloning and macOS support. A viable future option, particularly if its language coverage is needed; not installed or comparatively benchmarked here. |
| Qwen3-TTS 1.7B | Potentially higher quality, with a larger memory and inference cost on an 8 GB M1. Not the default for this installation. |

[Selected MLX checkpoint](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit), [MLX Audio](https://github.com/Blaizzy/mlx-audio), and [Whisper](https://github.com/openai/whisper). Exact model revisions are in `models.lock.json`. The Qwen license is included in `docs/QWEN-LICENSE.txt`; model cards ship beside the weights. MLX Audio and Whisper use MIT licenses. PySide6 is available under LGPLv3/GPLv3/commercial terms; bundled FFmpeg has its own distribution license. This is a local developer installation; preserve the relevant notices and review dependency terms before redistributing it. See `docs/DEPENDENCIES.md`.

The test sample's public-domain source and credits are in `samples/LICENSE.txt`. It is a test voice, not your voice. Use recordings you own or have permission to use.

## Final quality stabilization — 23 October 2026

New takes retain raw model audio, flag unconfirmed first/last words, and distinguish an
unchecked result from a passing ASR check. ASR does not certify phoneme completeness.
Failed regeneration keeps a previously valid selected take in use. Legacy checks remain
labelled for listening review; no old takes are automatically removed or re-recorded.

`[pause:n]` means exactly `round(n * 24000)` inserted silent samples. Existing natural
quiet is retained, so the acoustic gap may be longer. Inline placement requires offline
word alignment and a quiet interval. If neither can establish a safe cut, assembly stops
with a useful message; moving the marker between paragraphs avoids alignment.
Timing changes reuse compatible takes. See `docs/FINAL-QUALITY-REPORT.md` and the
offline listening page `samples/final-quality/index.html` for evidence and open issues.

Previews use the native macOS media backend and follow the system audio output
automatically. There is no in-app output selector. Recognition uncertainty appears in
the status area and section list; it does not open a completion popup or prevent
listening. Press Play or Full narration to hear the saved audio.
