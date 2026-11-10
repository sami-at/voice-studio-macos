# Incomplete words at phrase endings — investigation and fix (25 October 2026)

**Status: detection and regeneration implemented and measured; whether the endings now sound complete needs your listening** (`samples/endings/index.html`).

## Which narration

"Whydo flies — Hal Quality Final" (`c74f8c16`) has not been generated since it was created; it still holds the 23 October takes. The narration you most likely heard is the newest one, "Untitled narration" (`f516b218`, 25 Oct 16:33, 10 sections, Energetic Explainer). Both were checked.

## 1. Which words were incomplete

`f516b218`, by the new measurement of how the sound stops:

| Section | Last word | How it ended |
|---|---|---|
| 2 | "themselves" | the final **s** stops at full strength: 7 dB below speech, then silence |
| 5 | "mouth" | the **th** stops 21 dB below speech |
| 6 | "catch" | the **ch** stops 25 dB below speech |
| 1, 4, 8 | "fly?", "on", "properly" | **short ending**: stops 28–29 dB below speech, so the usual fade is missing. Borderline; for listening |
| 3, 7, 9, 10 | "interesting", "feet", "up", "dinner" | fade out naturally |

In `c74f8c16`, section 2 ("…behind **it**") and section 5 ("…its **mouth**") end cut. They will be caught and retried when that project is generated.

## 2. Where the defect originates: the Qwen3 model

Each stage was checked against the one before:

| Stage | Result |
|---|---|
| Processing (gain, 1.04× tempo) | The ending's energy survives to within ±0.6 dB in every section |
| Assembly | Every section's ending is copied bit for bit (difference 0.0) |
| Export | WAV and MP3 lengths match the narration; no clipping |
| Streaming decoder | Six takes were reproduced bit-identically, then the same codes were decoded with the full, non-streaming decoder. The audio is **identical** (difference 0.0), endings included |
| Codec frame boundaries | The cut falls at varying points *inside* the final 80 ms frame, not on a boundary. The model's last frame itself encodes "sound, then silence" |

So the model jumps from an audible sound straight to digital silence. This is an abrupt vocal cutoff, not processing, and not a naturally short pronunciation: ElevenLabs' phrase endings never drop more than 13 dB in 10 ms, while these drop 30–60 dB.

**How often:**
- Qwen3: in 150 fresh takes (10 sentences × 5 seeds × 3 conditions), **53 %** end cut. Natural vs Energetic, and a trailing line break in the text, made no difference.
- Words ending in a voiceless fricative or affricate are worst: "mouth" and "catch" were cut in **13 of 15** takes each.
- Chatterbox: **4 %** of 46 earlier takes, and **0 of 9** on the three hardest sentences.

## 3. What changed

- **`voice_studio/audio.py` `ending_stop()`:** measures the level at which a take's sound stops, relative to its own speech level, and how far it then falls within 10 ms. It takes multiple signals together and does not rely on the transcript.
- **`voice_studio/quality.py`:** two new flags.
  - **cut_ending** ("last word cut off"): a warning. The sound stops within 27 dB of speech level and falls 30 dB or more to silence. The take is marked "needs review" and **retried automatically** within the existing three attempts.
  - **short_ending**: a note only, for stops 27–35 dB below speech. Not retried.
- **Ranking:** if every attempt fails, the least-cut one is kept.
- **Worker bug fixed:** an older take verified before cut detection existed could be kept in preference to a regeneration. It is now judged by the current rule using its saved raw audio.
- **Unchanged:** the one-click workflow, resource safety, take preservation and exports. No fades, padding, stretching, breaths, pitch or volume changes were added.

**Why the word check missed it:** Whisper's confidence in the last word was a median **0.98** for cut takes, against 1.00 for complete ones, and 65 % of cut takes passed the word check. A transcript cannot prove every sound was spoken. Phoneme-level forced alignment would need a phoneme model that is not installed, and no new models were allowed.

## 4. Was it corrected?

Copy `9016595c` ("Untitled narration — complete endings") was regenerated through the app's real one-click path. The original `f516b218` is untouched.

| Section | Result |
|---|---|
| 2 "themselves" | Qwen3, retried, attempt 2 kept: fades out |
| 6 "catch" | Qwen3, retried, attempt 2 kept: fades out |
| 5 "mouth" | Qwen3 cut in all three attempts, so a **Chatterbox** take was used (verified, attempt 2): fades out |
| The other seven sections | Unchanged |

**Measured:** no section ends cut. Three short endings remain ("fly?", "on", "properly"). The WAV and MP3 exports (`samples/endings/narration-complete-endings.*`) decode at −18.1 LUFS and −1.5 dB peak, with no clipping. Peak memory was 4.0 GB (Qwen3) and 4.7 GB (Chatterbox).

**Not established:** that these now *sound* complete. Listen to the before and after for sections 2, 5 and 6, and judge whether the three short endings need anything.

## 5. Limitations that remain

- **Retries don't always help.** About half of Qwen3's takes end cut, so retries cost time, and three attempts do not always find a complete take ("mouth" and "catch" often need Chatterbox).
- **Chatterbox has its own flaw.** On very short lines it sometimes invents trailing syllables ("…a catch, built, direct-say"). The word check catches this and retries, but Chatterbox is about 10× slower.
- **Thresholds are provisional.** The −27 dB and −35 dB thresholds are judgements from measurement and need your listening to confirm.
- **Consistency across a mixed section.** The Chatterbox section can sound slightly different from its Qwen3 neighbours. The Review tab flags brightness differences of about 1.4× at the joins around it.
