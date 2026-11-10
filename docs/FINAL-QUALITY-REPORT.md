# Voice Studio final quality stabilization — 23 October 2026

**Assessment: not yet approved for production. Human listening is required.**

This pass fixes reproducible processing and reliability defects. It does not establish that either model always produces intact phonemes, natural delivery, or an identical voice across sections. Existing recordings cannot recover sounds already omitted by a model or removed by previous processing.

The full original Whydo flies script, with its standalone VDL pauses, is preserved in `samples/final-quality/whydo-flies.txt`. Open the [offline listening page](../samples/final-quality/index.html). All A/B processing pairs use the **same raw engine output**. Existing-project comparisons instead use the **same stored sections**, because those projects did not retain raw engine output. These are distinct experiments.

## Backup and preservation

Before implementation, the entire project was copied with macOS APFS copy-on-write cloning into `backups/final-quality-before/`: source, environment, installed models, references, profiles, sessions, selected takes, samples, historical reports, caches and prior backups. It is approximately 12 GB logically; shared disk blocks do not make it a hard link. `data-sha256.json` records the original 235 local-data files. This local backup protects against these edits, not failure of the physical drive.

No schema migration rewrites the user's existing projects. New metadata is additive. No original voice reference, authorization metadata, model, user take, project or backup is intentionally deleted. Test generation uses `samples/final-quality/`; GUI and integration tests use separate copied data directories there. Hal remains the default voice. Preservation is checked by hashes and selected-take IDs; final results are listed below.

## Confirmed defects and corrections

| Finding | Root cause | Change | Classification and evidence |
|---|---|---|---|
| Quiet attack/release audio removed during processing | `edge_trim()` detected activity relative to peak RMS, then kept just 100 ms around it. Quiet sounds longer than that guard were discarded. | Generated speech is no longer trimmed or faded in `polish_segment()`. It receives scalar gain and guard silence. New reference preparation trims only near-digital silence; existing references are unchanged. | **Fixed and verified** for reproduced sample loss. A known 900 ms signal became 699.667 ms after old processing, versus 900 ms now. This is a controlled acoustic fixture, not a claim that 200 ms of a particular user's word was missing. |
| Further quiet audio removed at assembly | A fixed amplitude threshold of 0.012 was treated as the speech boundary, keeping only 20 ms before and 25–60 ms after. | Assembly removes near-digital padding using 0.00001, preserves quiet signal and decay, and never overlaps sections. A separate quiet estimate only reduces added style silence; it never cuts samples. | **Fixed and verified** for reproduced sample loss: the old processed/assembled fixture retained only 579.958 ms of its 900 ms signal; the revised path retains 900 ms. Real same-raw clips and discard measurements are also supplied. Actual phonetic interpretation still needs listening. |
| Boundary fades can attenuate spoken samples | The first/last 6 ms were faded unconditionally, even if the raw recording began/ended with sound. Global mean subtraction also changed every sample, including quiet padding. | No unconditional fade or DC subtraction is applied to generated speech. Raw endpoints above the review threshold are flagged; silence does not stand in for missing phonemes. | **Fixed and verified** for destructive edge processing. A constant boundary test changed the old first/last samples to zero; the revised path preserves the entire signal under scalar gain. An actual model hard cut remains unresolved until a valid take is generated or heard. |
| One absent edge word could pass verification | `EDGE_SLACK=1` permitted a missing first or last aligned word. | Zero edge slack; substitutions/omissions are described as unconfirmed recognition, not proven speech loss. | **Fixed and verified** for the comparison blind spot. Deleting “Have” or the final word in the regression sentence passed before and fails now. ASR can still recognize a word whose phonemes are incomplete. |
| A passing retry could be discarded | Best-take selection compared coverage alone. A failed edge with greater coverage could outrank a passing result, then stop retries. | Rank passing checks first, then coverage and similarity. Maximum three attempts even if a larger count is requested. | **Fixed and verified** by deterministic regression tests. This ranking does not select the most expressive take. |
| A failed/unchecked regeneration could replace a valid selected take | `add_take()` always selected the newest result. | Preserve an existing compatible, verified selection if the new result fails or cannot be checked. Keep the new take and attempt evidence for review. | **Fixed and verified** in worker regression tests; real hybrid/selection integration results below. |
| Unchecked audio could display “Ready”; existing rejected selections were not surfaced on reassembly | UI treated `None` as success and ignored the worker's `unverified` event. | Show Unchecked, Check it, and Legacy check states; surface rejected selected takes on reassembly. Legacy approvals are not silently upgraded. | **Fixed and verified** in real Qt widget checks. Both saved full flies projects already contain an unconfirmed opening “Flies” in section 4. Neither file was replaced. |
| Inline pause could cut at the wrong word | Character fractions estimated time; the quietest nearby frame could be a zero crossing or a different word. | Map normalized expected words to offline Whisper word timestamps; require a quiet interval at the aligned boundary. If uncertain, refuse assembly with an actionable message. | **Improved but not fully resolved.** Guessing and cuts without a quiet interval are regression-tested out. ASR word alignment is approximate; naturalness and exact word placement need listening. Some takes may require a pause between paragraphs or regeneration. |
| Pause offsets drifted after whitespace normalization; adjacent marks could merge words | Offsets were computed before cleaning spaces, and deleting a pause inserted no separator. | Compute offsets against cleaned spoken prefixes and separate adjacent words. | **Fixed and verified.** The reproduced offsets `[8,13]` become `[3,7]` for “One two three.” |
| Timing edits unnecessarily invalidated inline takes | Legacy fingerprints included pause durations. | Add spoken-content fingerprints; reuse compatible legacy takes through validated recorded text/offset evidence. Never rewrite old hashes to bless stale audio. | **Fixed and verified** by storage and Qt tests. Changed spoken words still invalidate takes. |
| Editing a section dropped standalone pauses from the Script tab | Script reconstruction serialized words and paragraph flags but omitted `lead_pause`/`trail_pause`. | Serialize both boundary pause fields during section edits. | **Fixed and verified** by round-trip and Qt tests. |
| Malformed directions could reach TTS; long splitting could break a marker | Worker warned and continued; the splitter could break at spaces/colons inside VDL. | Reject malformed directions before synthesis; keep pronunciation markers indivisible, recognize pause-only lines without blank lines, avoid stranding common articles/prepositions at hard boundaries. | **Fixed and verified** by parser/splitter and Qt tests. The default 260-character target remains bounded; no blanket expansion of generation length. |
| Style gap calculation assumed padding that might not exist | Fixed kept-head/tail durations were subtracted even at a section's physical boundary. | Measure retained room; count natural quiet toward a style target without deleting it. | **Fixed and verified** in no-padding and quiet-room regressions. Style gaps remain acoustic estimates. |
| Language selection was ignored, and non-Latin expected text could normalize to empty | Qwen hardcoded English, Chatterbox used its default language, and recognition normalization accepted only ASCII letters. | Forward the saved language to each engine; retain Unicode words in verification. | **Fixed and verified** for parameter forwarding and false-empty comparisons. The real listening matrix is English; other languages are not perceptually certified. |
| Regenerating an older take with no seed could crash | Mirroring absent seed metadata sets the section seed to `None`; generation added an integer to it. | Fall back to the section’s deterministic seed when the saved seed is null, while retaining existing recordings. | **Fixed and verified** by a failing-before/passing-after worker regression (`legacy-seed-before.log`); the complete suite passes. |
| Switching a legacy take could crash the revised status display | Selecting an older take mirrors missing verification metadata as `None`; the new label compared that to an integer. | Treat absent/null verification versions as legacy in both table and take list. | **Fixed and verified** after reproduction in the real desktop take-switch check, then a passing full rerun and explicit null-metadata Qt regression. |
| Section actions clipped at the default width | All edit, take, engine and generation controls competed in one horizontal row. | Keep generation actions visible on a second row; allow the list/editor to scroll in small windows. | **Fixed and verified** with before/after screenshots and Qt bounds assertions at 1240×850 and 980×740. Colors and visual identity are retained. |
| Streaming optimization claims were unsupported by the installed Chatterbox code | The installed dependency accepts but ignores `stream` and `streaming_interval`. | Correct app documentation and comments; retain the existing engine and guidance configuration. | **Fixed and verified** as a documentation defect by local dependency inspection. No invented streaming speedup is claimed. |

Reproduction evidence: `samples/final-quality/reproductions/confirmed-bugs.json` and the WAVs alongside it. Regression tests: `tests/test_final_quality.py`. No change attempts to invent breaths, stretch a final consonant, correct pitch, or synthesize emotion.

## VDL timing contract

`[pause:n]` means **exactly `round(n × 24000)` inserted silent PCM samples**, in addition to natural quiet retained from the recordings. A 0.4-second marker inserts 9,600 samples. It does **not** promise a sample-accurate gap between perceived speech events. Acoustic boundaries depend on noise, breath, articulation and the measurement threshold.

Standalone boundary markers replace the style gap; they do not add a second style pause. Leading/trailing markers extend the opening/ending. Consecutive standalone markers add. Inline boundary markers also suppress an extra style gap. Inline timing edits reuse their source audio and saved word timestamps. Ambiguous inline placement is reported rather than silently cutting speech.

The Handbook and README now explain this definition. Prior reports measuring 0.364 s for a requested 0.4 s used an approximate total-gap policy; they are historical results, not evidence for the current inserted-silence contract. Pauses already present in a take remain audible, so some total gaps will be longer. This tradeoff is explicit and requires listening approval.

## Audio pipeline and application audit

- Synthesis remains mono 24 kHz; incompatible section formats are rejected. New raw output is retained losslessly as float WAV, processed sections as 24-bit PCM. Empty/nonfinite/non-mono output is rejected.
- Every speed setting uses FFmpeg's existing pitch-preserving `atempo` filter. Added leading/trailing guard silence protects the filter's edge windows; regressions exercise 0.75×, 1.04× and 1.25×. This preserves room for the signal and cannot recover a model omission.
- Assembly streams bounded blocks. Near-digital padding trimming and pause estimates are separate. No spoken sections overlap or crossfade. Output replacement stays atomic, including when pause alignment, staleness or format validation fails.
- WAV export remains the signal reference. Existing loudness normalization and MP3 encoding were preserved; no new EQ, denoising, compression, limiter, pitch matching or voice effect was added. Codec comparisons align decoded MP3 to exported WAV and record sample counts, correlation, delay and peaks.
- Old projects and takes stay on disk and retain their selections. Timing-only reuse does not require loading a TTS engine. The worker still supports resume, section regeneration and cancellation; integration and desktop results below document which paths actually ran.
- Engine release now collects Python reference cycles before clearing the MLX cache. Tests and the real generation matrix serialize engines. No model download, paid API or cloud processing is used. Real model tests run under the macOS network-denial profile in `docs/deny-network.sb`.
- Reference identity is pinned to the existing profile/reference path. Original reference files are copied for listening and hash comparison; no original Hal or Mike recording is edited. Mixed-engine output explicitly warns about timbre/accent differences.

## Model and perceptual findings still open

| Concern | Classification | What is and is not established |
|---|---|---|
| Missing model-generated first/final phonemes | **Model limitation / Requires human listening** | Strict text alignment and raw endpoint flags can catch some failures. Whisper word agreement cannot certify every consonant or release. Raw waveform and before/after stages are supplied. |
| Curious/playful/surprised delivery | **Model limitation** | No new emotion controls, style prompts, emphasis effects or claims that punctuation creates emotion. Punctuation and context can affect a take without delivering dependable emotional direction. |
| Smooth connected prosody across sections | **Improved but not fully resolved / Requires human listening** | Avoidable processing cuts and extra style silence are addressed; independently generated phrases can still change energy, pitch, timbre and cadence. |
| Hal identity across Qwen/Chatterbox | **Requires human listening** | Original references are available beside the matrix and mixed examples. Statistical scores are not treated as identity approval. No artificial matching is applied. |
| Playback buffering removing audible speech | **Not reproduced** unless an explicit test below says otherwise | Processing defects are distinct from the Qt backend/device path. A moving playback clock cannot establish that every attack was heard on the physical device. |
| MP3-only word/phoneme loss | **Not reproduced** unless codec results below say otherwise | Decoded alignment and sample counts test transport integrity, not phonetic naturalness. |
| Best universal chunk size | **Requires human listening** | The existing bounded default is retained. The full real script's intentional paragraph boundaries are preserved. Chunk benchmarks are evidence to review, not a claim that the longest or shortest chunk sounds best. |

## Test results and performance

The original baseline was **109 passing unit tests**. Two former expectations deliberately changed: permitting one missing edge word, and assuming edge-trimmed section duration. Their replacement tests enforce the requested stricter behavior. The known “must”/“most” recognition ambiguity is now explicitly uncertain rather than automatically approved. No test is skipped to imply acceptance.

### Automated and desktop validation

- **142 unit tests passed**, no failures or skips, after the final legacy-seed correction (`unit-tests.log`). Baseline: 109. New regressions cover destructive edge processing, strict edges, ranking/retries, safe cuts, malformed VDL, timing reuse, stale assembly, language forwarding and cycle release.
- **Nine isolated Qt quality checks passed** (`gui-quality-results.json`): default Hal, timing reuse, section timing preservation, syntax errors, uncertainty labels, null legacy metadata, Handbook search, rejected-selection warnings and visible controls at both tested sizes. Screenshots: `gui-quality-before.png` and `gui-quality.png`.
- **Full desktop/media check passed** (`desktop-check/gui-results.json`, `desktop-recheck.log`): playback, pause, seeking, waveform, reference/section previews, switching sources while paused, engine settings, take selection without synthesis, voice switching, orphaned projects and reopening. The selected working output was “oraimo Necklace Lite”; two outputs were enumerated. There were 236 responsiveness timer ticks during real generation; cancellation completed in **0.245 s** and preserved completed audio. This is one device/run, not a claim about every audio device or physical audibility.
- **Real worker integration passed** (`integration-results.json`): two Qwen sections, replacement of section 2 with Chatterbox, a real bounded retry (second attempt selected), preserved earlier take and neighboring section, mixed-engine warning, switching back, timing edit, resume and both exports. Qwen job: **21.502 s**, peak MLX **3.622 GB**. Chatterbox job including two attempts: **49.067 s**, peak **4.433 GB**. Timing-only reassembly: **0.366 s**; resume: **0.138 s**, both with no TTS-load/section-generation events and **0 GB MLX allocation** reported.
- The initial isolated integration attempt failed because its new HF cache lacked the existing local S3 tokenizer. Copying the installed cache into the test library fixed the fixture; no download occurred. The first full desktop run exposed a real null-metadata crash introduced by the new status label; that was fixed and both desktop and targeted checks rerun successfully. Original failed logs are retained (`desktop-check.log`; the initial integration failure also remains in `validation-jobs.json`, while `integration-results.json` records the successful rerun).
- Historical generation/demo scripts are not represented as newly passing wholesale. The isolated matrix and integration exercises cover their relevant paths without overwriting original samples or projects. The old direction check's acoustic-gap bounds are historical and do not validate the new inserted-silence contract.

### Real-audio matrix and unresolved recognition

**92 fixed-seed raw recordings** cover Hal/Mike × Qwen/Chatterbox × Natural/Energetic. Each combination includes all eight original Whydo sections and its standalone pauses. Each Natural case also has seven challenges: short endings, quiet attacks, repeated words, pronunciation overrides and inline timing. There are **eight full single-engine A/B narrations, four mixed-engine A/B narrations and two existing-project A/B narrations**, each with WAV and MP3 exports.

These diagnostic captures intentionally keep one deterministic take per input so A/B processing is comparable; they do not apply the application's retry selection. All raw files, processed stages, full assemblies and recognition transcripts remain available. ASR pass counts below use the current strict comparison for all three stages; “before” means the old audio processing, not the old lenient verifier.

| Case | Takes | ASR passes raw / before / after | Generation seconds | Raw audio seconds | Generation/audio | Peak MLX GB | Peak RSS GB |
|---|---:|---:|---:|---:|---:|---:|---:|
| hal-chatterbox-energetic | 8 | 7 / 7 / 5 | 416.30 | 42.52 | 9.79× | 4.747 | 1.235 |
| hal-chatterbox-natural | 15 | 12 / 12 / 11 | 865.33 | 70.44 | 12.28× | 4.752 | 1.230 |
| hal-qwen3-energetic | 8 | 7 / 7 / 7 | 45.53 | 35.76 | 1.27× | 3.843 | 1.194 |
| hal-qwen3-natural | 15 | 13 / 13 / 13 | 75.25 | 63.20 | 1.19× | 3.846 | 0.555 |
| mike-chatterbox-energetic | 8 | 7 / 7 / 7 | 351.62 | 41.36 | 8.50× | 4.771 | 0.708 |
| mike-chatterbox-natural | 15 | 11 / 11 / 11 | 686.01 | 68.80 | 9.97× | 4.731 | 1.361 |
| mike-qwen3-energetic | 8 | 7 / 7 / 7 | 42.39 | 34.56 | 1.23× | 3.843 | 1.453 |
| mike-qwen3-natural | 15 | 14 / 14 / 14 | 78.77 | 60.16 | 1.31× | 3.843 | 0.651 |

**78/92** raw and old-processed takes pass the text check; **75/92** revised-processed takes pass. This is **not an ASR accuracy improvement claim**. Seventeen revised takes have text uncertainty; fifteen raw takes have a nonquiet endpoint, with one overlap: **31/92 source takes require review**. Raw endpoint flags do not prove an omitted phoneme. Full-narration ASR can conceal individual section-edge substitutions, so it must not override the section flags.

Three changed recognition results deserve first listening priority: Hal/Chatterbox/Energetic section 2 (“You” → “He”) and section 8 (“clean” → “queen”), and Hal/Chatterbox/Natural challenge section 10 (“it” unconfirmed). The raw and old-processed versions passed recognition. Changed padding/gain and tempo-filter windows can change recognition; this does not establish which version sounds better. Natural processing retains the original waveform under scalar gain, so its changed transcript alone is not evidence that a sample was cut. These cases remain open for listening, including the possibility of a perceptual processing regression.

Common remaining flags concern “Flies” versus “Fly/Blies/Boys” and phonetic overrides transcribed as ordinary words. Do not automatically approve or forcibly rewrite these. The listening page shows all flagged source sections and original references. No claim of complete initial/final phonemes, click-free transitions, matched identity, or dependable emotional delivery is made.

### Pause and export measurements

- Mike Natural inline placement succeeded with both engines. Against the same unpaused source assembly, each `[pause:0.4]` added **exactly 9,600 frames at 24 kHz**. Both Hal versions of the same inline sentence were refused because the aligned boundary lacked a safe quiet interval: **two successes, two safe refusals**. Inline placement is therefore **improved but not fully resolved**, with a usability limitation that remains open.
- In the real integration narration, changing the standalone pause from 0.4 to 0.7 seconds added **exactly 7,200 frames**, with the same selected Qwen recordings. Resuming retained the exact assembled frame count (`pause-measurements.json`). Regression fixtures also test standalone, boundary, repeated, leading and trailing markers.
- **28 WAV/MP3 export pairs** were decoded to the same 24 kHz reference rate. Twenty-six had identical frame counts. Old Hal/Qwen/Energetic MP3 had 14 extra decoded frames (0.583 ms); revised Mike/Chatterbox/Natural had four extra frames (0.167 ms). No pair was shorter. Estimated delay was 0 ms at the 0.25 ms measurement resolution; waveform correlation rounded to 1.000000 at six decimals in the subsampled comparison. MP3 is still lossy, not sample-identical. Peaks remained below full scale. These checks did not reproduce MP3-only word loss.
- Retaining natural quiet makes some revised narrations longer, especially Chatterbox. The full Hal/Chatterbox/Natural assembly grows from about 43.75 to 47.89 seconds, and Energetic from about 39.99 to 43.84 seconds. This reflects the preservation and explicit-pause policies, not proof of better flow. Listen for excessive gaps before approving this tradeoff.

### Chunk-size and resource findings

The benchmark flattens the first five connected Whydo paragraphs for generation, allowing different chunk targets to be compared without changing the user's saved script. One seeded run per target/engine, Hal reference:

| Engine | Character target | Sections | Generation seconds | Audio seconds | Peak MLX GB | ASR-passing sections |
|---|---:|---:|---:|---:|---:|---:|
| chatterbox | 160 | 4 | 138.30 | 24.48 | 4.778 | 4/4 |
| chatterbox | 260 | 2 | 114.37 | 21.76 | 4.944 | 2/2 |
| chatterbox | 380 | 2 | 123.42 | 23.28 | 4.948 | 2/2 |
| qwen3 | 160 | 4 | 48.13 | 23.28 | 3.846 | 4/4 |
| qwen3 | 260 | 2 | 24.66 | 20.96 | 3.846 | 2/2 |
| qwen3 | 380 | 2 | 26.76 | 23.28 | 3.846 | 2/2 |

Retain the **260-character default**. In this limited run it halves the 160-target section count, has the lowest measured generation time in both engines, and Qwen's two sections have complete recognized words. Increasing to 380 did not reduce the section count further and did not establish a quality advantage. The Chatterbox text check still accepts some internal substitutions at its existing coverage threshold; edge strictness is not universal word-perfect certification. Benchmark recordings are on the listening page.

The Mac has **8 GiB physical memory**. Matrix peak MLX allocations were **3.846 GB Qwen** and **4.771 GB Chatterbox**; the long-chunk benchmark reached **4.948 GB Chatterbox**. Matrix process RSS ranged **0.555–1.453 GB**. MLX and RSS are different accounting views of unified memory and must not simply be added. The ASR comparison process peak RSS was **0.539 GB**.

A system observation during Chatterbox capture recorded **20,244.69 MB swap used**, 21,504 MB allocated and 27% free memory (`hardware-observation.json`). Other applications remained open; this is not attributable solely to Voice Studio. Successful serial runs do **not** establish a comfortable no-swap working set on an 8 GB Mac. Qwen took roughly **1.19–1.31 seconds per audio second** in the matrix; Chatterbox **8.50–12.28**. No performance speedup is claimed. Stronger rejection can cause more retries, up to three, increasing latency. Model settings remain unchanged and only one TTS engine is retained at a time.

### Final preservation and launch

The updated application was launched successfully against the original library after a normal Qt close, with process **90811** and a new desktop lock. The offline listening page was also opened. No process was force-killed to restart the user's app.

`preservation-results.json` confirms **all ten original project JSON files are identical**, including their selected-take IDs. All original audio/reference/authorization content, draft and stored take files are preserved. **232 of 235 original local-data files remain byte-identical**. The three expected changes from app restart are the desktop process lock, appended desktop log and Hal's profile `updated` timestamp; all other Hal profile fields are unchanged. Mike's entire profile is unchanged. Hal remains default. No original file is missing. All **235 backed-up file hashes match** the pre-change manifest.

Exact source changes are recorded in [source-changes.patch](../samples/final-quality/source-changes.patch) and [changed-files.json](../samples/final-quality/changed-files.json). Nothing in this report treats an automated pass as listening approval.

### Listening review index

Section numbers 1–8 refer to the Whydo script; 9–15 are Natural-style challenges.

| Case | Section | Uncertainty |
|---|---:|---|
| hal-chatterbox-energetic | 2 | Unconfirmed: you |
| hal-chatterbox-energetic | 4 | Unconfirmed: flies |
| hal-chatterbox-energetic | 8 | Unconfirmed: clean |
| hal-chatterbox-natural | 4 | Unconfirmed: flies |
| hal-chatterbox-natural | 10 | Unconfirmed: it |
| hal-chatterbox-natural | 12 | Unconfirmed: flies |
| hal-chatterbox-natural | 14 | Unconfirmed: tar, sigh, clee, eye |
| hal-qwen3-energetic | 1 | Raw head reaches boundary |
| hal-qwen3-energetic | 4 | Unconfirmed: flies |
| hal-qwen3-energetic | 6 | Raw head reaches boundary |
| hal-qwen3-natural | 4 | Unconfirmed: flies |
| hal-qwen3-natural | 14 | Unconfirmed: tar, sigh, new, clee, eye |
| hal-qwen3-natural | 15 | Raw tail reaches boundary |
| mike-chatterbox-energetic | 4 | Unconfirmed: flies |
| mike-chatterbox-natural | 4 | Unconfirmed: flies |
| mike-chatterbox-natural | 9 | Unconfirmed:  |
| mike-chatterbox-natural | 14 | Unconfirmed: new, clee, eye |
| mike-chatterbox-natural | 15 | Unconfirmed: a |
| mike-qwen3-energetic | 4 | Unconfirmed: flies; Raw head reaches boundary |
| mike-qwen3-energetic | 8 | Raw tail reaches boundary |
| mike-qwen3-natural | 1 | Raw head reaches boundary |
| mike-qwen3-natural | 2 | Raw head reaches boundary |
| mike-qwen3-natural | 3 | Raw head reaches boundary |
| mike-qwen3-natural | 4 | Raw head reaches boundary |
| mike-qwen3-natural | 5 | Raw head reaches boundary |
| mike-qwen3-natural | 8 | Raw head reaches boundary |
| mike-qwen3-natural | 9 | Raw head reaches boundary |
| mike-qwen3-natural | 10 | Raw head reaches boundary |
| mike-qwen3-natural | 13 | Raw head reaches boundary |
| mike-qwen3-natural | 14 | Unconfirmed: new, clee, eye |
| mike-qwen3-natural | 15 | Raw head/tail reaches boundary |


## Safe cleanup audit

No cleanup was performed. Approximate pre-test sizes: experimental models 3.9 GB, required Chatterbox 2.5 GB, Qwen 1.9 GB, Whisper 137 MB, repair wheels 740 MB, Python environment 2.6 GB, local cache 472 MB, sessions 48 MB, voice library 3 MB, logs 256 KB, prior local backups 12 MB. Test recordings and retained raw attempts add disk use. Experimental models, caches, installers and recordings have not been removed on the assumption that they are unused. Any model deletion would need a concrete separate review.

## Code changed

`voice_studio/audio.py`: conservative signal preservation, raw boundary diagnostics, aligned pause insertion, separate style-room estimation, stale-assembly guard.

`voice_studio/verify.py`: strict edges, candidate ranking, uncertainty wording.

`voice_studio/worker.py`: raw retention, word timings, bounded retries, legacy-seed fallback, preserved valid selections, alignment for reused takes, review/mixed-engine warnings.

`voice_studio/storage.py`: additive spoken fingerprints and timing metadata, validated legacy compatibility.

`voice_studio/direction.py` and `text.py`: cleaned pause offsets, safe marker splitting/validation, standalone line handling, complete timing serialization, conservative phrase boundaries.

`voice_studio/ui.py`: timing-only reuse, preserved section timing, clear uncertainty, malformed input handling, review events, legacy-null compatibility and visible section actions. No visual redesign.

`voice_studio/engines.py`: saved-language forwarding, reference-cycle release and truthful streaming/identity descriptions. Model configuration and sampling settings are preserved.

`voice_studio/handbook.py`, `styles.py`, `README.md`: accurate timing and capability descriptions.

`tests/test_core.py`, `tests/test_final_quality.py`, `pytest.ini`: changed-contract assertions and regression coverage; test discovery excludes the full project backup.

`scripts/final_quality_*.py`: reproducible isolated capture, comparisons, chunk benchmarks, GUI/integration tests and evidence. `scripts/direction_check.py`: timing-only edits now expect reuse; its historical acoustic-gap checks are not current acceptance evidence. `scripts/gui_check.py`: configurable report directory and restored-project engine assertion.

## Production decision

Do not label this application finalized or perfect. Technical defects can be fixed without proving perceptual acceptance. The final gate is a script-guided listen to the original references, before/after sections, complete Whydo narrations and mixed-engine transitions. Record any objection by case, section, word and timestamp. A questionable take must be regenerated or left marked for review; padding or ASR coverage is not a substitute for complete speech.


## Follow-up: silent playback after device disconnect — 23 October 2026

The user's new Qwen narration (`65df09f37cfc40ca93b50230b0e03f62`) was successfully saved: 38.274 seconds, peak 0.861 and RMS 0.102. Section 4 remained uncertain after three attempts: recognition heard “Fly” instead of “Flies.” That warning does not mute audio and has not been bypassed.

The desktop log reported that the cached CoreAudio device could no longer be found. At investigation time macOS offered only MacBook Air Speakers, with output volume 50% and mute off. The app retained its initial `QAudioOutput` device and did not subscribe to device changes. **Confirmed playback-routing defect, fixed:** keep a `QMediaDevices` listener, follow changes to the system output, resolve the current device before each playback, and fall back to the system output when an explicitly selected device disappears. The same QAudioOutput object is retained. A compact Output selector allows a manual override; System output remains the default for normal speaker/Bluetooth switching. This follows macOS routing rather than changing the system's output preference.

The completion warning now says recognition could not confirm words, that audio was saved, and how to play it. A stalled player no longer claims that the audio is definitely fine or that a Bluetooth device must be at fault.

**Verification:** 147 tests passed, including five routing regressions. The actual saved narration and section preview advanced through MacBook Air Speakers with no Qt media error. A simulated device-disconnection signal reset an unavailable explicit choice to the system device; switching source after seeking and control visibility at 1240×850 and 980×740 passed. Physical Bluetooth unplug/reconnect and perceived audibility still require the user's confirmation. Evidence: `samples/playback-fix/` (unit log, Qt log, routing results, UI screenshot and preservation check). Current source and library were copied to `backups/playback-before/` first. No source recordings or project/take selections were changed.

During validation, importing Qt inside the restricted execution sandbox aborted a **test process (PID 91659)** and produced the macOS “Python quit unexpectedly” dialog. The user's app (PID 90811) remained running. Tests were rerun successfully with local Qt access and network denied. This was a test-environment crash, not loss of the narration. The app was subsequently closed normally and relaunched with the fix.


## Follow-up: native preview and system-only routing — 23 October 2026

The user reported that the first routing fix did **not** restore audible previews. The earlier playback-clock checks were insufficient evidence of audibility. A five-second excerpt of the latest saved narration (`2ba2d3fa509d4c37849199af710cc2e3`) was played through macOS `afplay`; **the user confirmed hearing the voice**. This establishes that this recording and the native system playback path can produce audible speech. It does not identify the exact internal cause of the Qt FFmpeg preview failure.

The app now defaults to the **installed native macOS/Darwin Qt multimedia backend** for previews. Plugin loading was confirmed in `samples/playback-system/qt-playback.log`. FFmpeg remains the audio conversion/export tool; no recordings or generated samples were transformed for this fix. Per the user's request, the output selector was removed entirely: previews always follow the system default, including speaker/Bluetooth changes managed by macOS.

The generation-completion recognition popup was removed. Uncertain takes remain marked for review in Sections, and completion shows a nonmodal “Audio saved” status with recognition details in its tooltip. The verifier still reports the unconfirmed “Flies” in section 4; it is not silently approved. Playback controls remain available without dismissing a dialog.

**Validation:** 147 unit tests pass. A real Qt check with the latest narration confirms the native backend loads, no output selector exists, an unverified completion opens no warning dialog, playback and source changes after seeking advance, and controls fit both window sizes. The full desktop check also passes with native playback, reference/section previews, take switching, saved settings, project reopening and real generation cancellation (0.188 s, 414 heartbeat ticks). These automated checks still do not certify physical audibility; the user subsequently confirmed hearing the replay through Voice Studio’s revised native preview. Audibility is confirmed for this narration on the current system output; this does not certify all devices or narration quality. Evidence and preservation checks are in `samples/playback-system/`; the pre-change source/library snapshot is `backups/playback-system-before/`.

## Follow-up: user-approved energetic word endings — 23 October 2026

**Specific endings repaired and verified by listening:** The user reported shortened “together” in original section 2 and “themselves” in original section 4, in both individual playback and the full narration. They accepted the ending of “themselves” in fresh Qwen/Hal take seed 2046. They rejected isolated “together” take seed 1044, then accepted “together” in seed 3044, generated with the next sentence included. Both accepted recordings retain the original Energetic Explainer settings: reference tempo 1.15 and final speed 1.04. Natural-reference and faster-output substitutes were rejected by the user and were not selected.

**Diagnosis and limits:** Reassembling the original project was sample-identical to its saved full narration. Assembly discarded zero nonzero samples from both reported sections. Removing output tempo processing did not resolve the perceived “together” ending. Repeating the original synthesis with the same reference and seed reproduced the raw audio exactly. These observations point to generated articulation rather than assembly truncation. The accepted contextual generation also uses a different seed, so this comparison does not establish context as the sole cause or guarantee future endings. ASR recognized “together” even in a take the user rejected; word coverage is not a phoneme-completeness test. Earlier cropped comparison excerpts introduced an invalid mid-phrase onset; subsequent listening used complete sentences.

**Saved repair:** `local_data/sessions/b3daa1e66e474c45a1bcf501ec03c4e3/project.json`, titled **Whydo flies — Energetic repaired**, contains seven sections and a 38.2275-second narration. Original sections 2 and 3 are one intact approved recording. The aligned splitting helper found no safe quiet interval, so no internal audio cut was made. Script words and standalone explicit pauses remain unchanged; the paragraph break between the two connected sentences was removed in this copy. Other selected recordings are unchanged. Original sections 2 and 3 and their take metadata are archived in the copy, and the entire source project is untouched. The original “themselves” take remains available alongside its approved replacement. All copied recordings have independent paths under the new project.

**Preservation and checks:** `scripts/save_approved_endings.py` creates this additive repair and records evidence. Before creation, the source project and draft were backed up in `backups/approved-endings-before/`. All 148 existing project and voice files matched their pre-repair hashes after saving. Each assembled section discarded only zero-valued samples. The repaired script splits back into the same seven sections with the same explicit pauses; no selected take is stale. A temporary-library native Qt check reopened the repaired project, confirmed selected seeds 3044 and 2046, the available previous take, enabled playback, 38.227-second media duration, and advancing muted playback with no error. An initial offscreen check did not load media duration; the native desktop check passed. This muted check adds no new human audibility claim. The existing 147-test result belongs to the earlier source changes; no production Python module changed for this specific repair. Voice Studio was closed normally, its latest draft backed up, and reopened on the repaired copy.

**Improved but not universally resolved / requires listening:** User approval covers the reported word endings, not every phoneme or the complete assembled narration. The contextual take retains its raw-onset diagnostic flag. Recognition of the “themselves” take still spells the opening as “FLYS” rather than “Flies”; its ASR review flag remains. These are now sections 2 and 3 in the repaired copy. Neither flag is silently overridden by the listening approval. No new model, artificial phoneme stretching, decoder replacement, or global style change was introduced. General model articulation and the remaining acceptance matrix are not certified production-ready.

Evidence: `samples/edge-followup/listening-feedback.json`, `diagnosis.json`, `assembly-evidence.json`, `02-03-energetic-context.json`, `energetic-candidates.json`, `saved-repair.json`, and `repair-ui-check.json`. Complete repaired WAV and MP3 exports are `samples/edge-followup/narration-repaired.wav` and `narration-repaired.mp3`; original, rejected, and accepted diagnostic recordings are retained alongside them.
