# Voice Direction Language: what was measured

22 October 2026, on this Mac (M1, 8 GB). One sentence split by each mark, three takes per
mark per engine, voice Hal. The gap is the longest silence inside the line.

## Punctuation and the pause it produces

| Mark | Engine | Mean gap | Range over three takes | Line length | All words present |
| --- | --- | --- | --- | --- | --- |
| `,` (comma) | Qwen3-TTS | 0.351 s | 0.294–0.437 s | 3.28 s | yes |
| `.` (period) | Qwen3-TTS | 0.226 s | 0.215–0.232 s | 3.23 s | yes |
| `...` (ellipsis) | Qwen3-TTS | 0.217 s | 0.135–0.284 s | 3.44 s | yes |
| ` —` (emdash) | Qwen3-TTS | 0.260 s | 0.130–0.339 s | 3.79 s | yes |
| `;` (semicolon) | Qwen3-TTS | 0.221 s | 0.167–0.268 s | 3.36 s | yes |
| `:` (colon) | Qwen3-TTS | 0.233 s | 0.113–0.335 s | 3.39 s | yes |
| `?` (question) | Qwen3-TTS | 0.312 s | 0.286–0.357 s | 3.47 s | yes |
| `!` (exclaim) | Qwen3-TTS | 0.182 s | 0.128–0.214 s | 3.57 s | yes |
| `?!` (both) | Qwen3-TTS | 0.299 s | 0.216–0.410 s | 3.49 s | yes |
| `,` (comma) | Chatterbox | 0.391 s | 0.295–0.537 s | 3.87 s | yes |
| `.` (period) | Chatterbox | 0.276 s | 0.153–0.402 s | 3.77 s | yes |
| `...` (ellipsis) | Chatterbox | 0.323 s | 0.172–0.466 s | 3.76 s | yes |
| ` —` (emdash) | Chatterbox | 0.340 s | 0.215–0.473 s | 3.96 s | yes |
| `;` (semicolon) | Chatterbox | 0.323 s | 0.172–0.466 s | 3.76 s | yes |
| `:` (colon) | Chatterbox | 0.391 s | 0.295–0.537 s | 3.87 s | yes |
| `?` (question) | Chatterbox | 0.345 s | 0.299–0.415 s | 3.73 s | yes |
| `!` (exclaim) | Chatterbox | 0.251 s | 0.142–0.344 s | 4.28 s | **no** |
| `?!` (both) | Chatterbox | 0.420 s | 0.216–0.541 s | 4.67 s | yes |

### What this supports

* **Punctuation does lengthen the gap, but imprecisely.** On Qwen3 a comma reliably beat a
  full stop (0.294–0.437 s against 0.215–0.232 s, no overlap) — the opposite of what most
  people expect. Everything else overlaps take to take.
* **Qwen3's full stop is the steadiest mark**, 0.215–0.232 s across three takes.
* **Chatterbox folds marks together.** `;` and `…` produced byte-identical audio, as did `:`
  and `,`. Its ranges are wide (a full stop spanned 0.153–0.402 s), so punctuation is a poor
  timing control there.
* **No mark changes intonation.** Final-pitch slope for `?` against `.` was -44.5 vs -39.0 on
  Qwen3 and -13.1 vs -14.0 on Chatterbox: both falling, no question rise. This matches the
  earlier five-seed test where the effect ran in opposite directions for different voices.
* **`!` carries a small risk on Chatterbox**: one take of three dropped a word.

## Emphasis markers

`*important*` and `CAPITALS` were tested against the plain sentence at the same seed.

* The asterisks are **not spoken aloud** — the transcription comes back clean.
* The audio **does change**, but only the way a different seed changes it. There is no
  evidence of emphasis on the marked words.
* On Chatterbox both forms produced a word substitution (`are` heard as `were`).

Neither is implemented. Voice Studio will not fake emphasis with a loudness or pitch boost.

## What is implemented, and how exact it is

| Mark | Mechanism | Measured |
| --- | --- | --- |
| `[pause:n]` | Voice Studio inserts the silence when assembling, so the engine is not involved | `[pause:0.8]` gave **0.771 s** on Qwen3 and **0.782 s** on Chatterbox, against 0.111 s and 0.102 s without it. `[pause:0.6]` through to the exported file gave **0.595 s** |
| `{written\|spoken}` | Text substitution before the engine sees it | Script keeps “tarsi”; the engine received and spoke “tar sigh” |
| `[say:word]` | Same, applied to the word before the marker | As above |

Silence already present at the cut counts towards the requested pause, so a pause is never
added on top of one the model produced. A section's fingerprint covers the spoken text **and**
its pause offsets, so changing a pause or a pronunciation marks that section's takes stale
without deleting them.

Completeness is checked against the spoken text, never the raw markers.

## A pause marker on its own line

A paragraph containing only `[pause:n]` is a boundary between sections, not a section. It used
to become a section with nothing to say, which failed with *“Section 2 has no words to speak.”*

| Script | Result |
| --- | --- |
| `…that?` / `[pause:0.4]` / `Here's…` | Two sections. Measured gap **0.364 s** on Qwen3, **0.400 s** on Chatterbox |
| `[pause:0.5]` before the first words | Lengthens the opening by that amount |
| `[pause:0.7]` after the last words | Lengthens the ending by that amount |
| Markers on consecutive lines | Add up (0.3 + 0.2 becomes 0.5) |
| A script of nothing but markers | No sections, and nothing is sent to the engine |

The pause **replaces** the style's paragraph gap rather than adding to it, so the length asked
for is the length heard. Because the marker never belongs to a section, a section's fingerprint
does not change when the timing does: editing only the pause keeps the existing takes and simply
reassembles.
