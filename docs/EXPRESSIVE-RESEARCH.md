# Expressive voice cloning: research and benchmark

21 October 2026, measured on this Mac (M1, 8 GB). Nothing in the application was changed by
this work; the candidate sits unwired in `models/evaluation/`.

## The short answer

**No model I could find combines reliable instruction-driven emotional delivery with reference
voice cloning under a licence that permits commercial use.** Every candidate fails at least one
of those three, and the failure is structural rather than a matter of tuning.

I am not going to tell you this is solved. It is not.

## Why it keeps failing: instruct competes with the reference

The pattern is the same in every architecture tested. An instruction tells the model **who is
speaking** — pitch centre, apparent age, brightness. A reference recording tells it the same
thing, far more precisely. When both are present, the reference wins and the instruction has
nothing left to control.

Measured on VoxCPM2 with the same sentence:

| With Hal's reference | Without any reference |
| --- | --- |
| "curious", "surprised", "confident", "playful" moved pitch range by **less than the seed-to-seed spread** | "deep, calm" produced the lowest pitch of the run, **103 Hz** |
| Hal's identity held at **0.914–0.955** across all 15 takes | "bright, energetic, quickly" gave the two **highest** pitches (215, 234 Hz) and the fastest rates |

So the instruction *does* work — as a voice designer. It is not a performance director. Cloning
and instructing are competing for the same control, which is exactly the limitation you already
identified with the Qwen3-TTS variants, appearing again in a different shape.

## Candidates

All eighteen TTS families in the installed `mlx-audio` were searched for a `generate()` that
accepts an emotion-like argument **and** a reference recording. Nine matched. Each was then
checked for whether the instruction survives on the cloning path, whether an Apple-Silicon
checkpoint exists, and what the **weights** are licensed under — not the code.

| Model | Clone + instruct together? | Weights licence | Commercial | Verdict |
| --- | --- | --- | --- | --- |
| **VoxCPM2** (openbmb) | Yes, structurally | **Apache-2.0**, "free for commercial use" | Yes | **Benchmarked.** Instruction did not change delivery while cloning |
| **OmniVoice** (k2-fsa) | Yes — instruct and reference share one prompt | **CC-BY-NC** | **No** | Eliminated. The best architecture of the set, and unusable |
| **Breeze-TTS-2** | Yes | research / non-commercial only | **No** | Eliminated |
| Chatterbox v3 | Yes (`exaggeration`) | MIT | Yes | Already integrated. Control measured unreliable |
| Qwen3-TTS Base | No — `instruct` rejected | Apache-2.0 | Yes | Current default engine |
| Qwen3-TTS VoiceDesign / CustomVoice | No — no `ref_audio` at all | Apache-2.0 | Yes | Cannot use your voices |
| F5-TTS | No instruct | CC-BY-NC | **No** | Eliminated earlier |
| Zonos v2 (MLX port) | No emotion argument exposed | — | — | Port omits the emotion vector |
| Higgs Audio v3, VibeVoice, Spark, Sesame, IndexTTS | No instruct argument | — | — | Cloning only |

### The licence trap, twice

You warned not to assume a code licence covers the weights. That warning paid for itself:

- **OmniVoice** is published as `mlx-community/OmniVoice-8bit` tagged **`apache-2.0`**. Its own
  model card says: *"Our code is released under the Apache 2.0 License. **The pre-trained model
  is licensed under the CC-BY-NC** due to constraints from its training data (e.g. Emilia)."*
  The MLX conversion carries the code licence, not the weight licence. Its audio tokenizer adds
  a third licence (Boson Higgs Audio 2, derived from Meta Llama 3).
- **Breeze-TTS-2** is tagged `other`: *"model weights, derivative models, and self-hosted outputs
  are for research and non-commercial use only."* Its source code is Apache-2.0.

Both would have looked commercially usable from the tag alone.

## VoxCPM2 benchmark (`scripts/expressive_check.py`)

Five instructions, three seeds each, same sentence, Hal's reference, on this Mac.

| Instruction | Pitch movement (semitones) | Loudness range (dB) | Words/sec | Hal identity |
| --- | --- | --- | --- | --- |
| neutral (no instruction) | 4.69 | 11.98 | 3.45 | 0.94 |
| curious | 4.35 | 11.30 | 3.35 | 0.93 |
| surprised | 4.37 | 10.62 | 3.14 | 0.94 |
| confident | 5.17 | 11.98 | 3.35 | 0.93 |
| playful | 3.93 | 11.08 | 3.24 | 0.92 |

**No instruction separated from neutral.** Within one instruction the takes ranged as widely as
3.58–6.37 semitones (confident), which is larger than any gap between instructions. Seed
variation dominates, so these numbers cannot distinguish direction from chance.

What VoxCPM2 *does* do well:

| | Result |
| --- | --- |
| Voice identity | Hal held at **0.914–0.955** across every take, including the dramatic ones |
| Word completeness | **15 of 15** takes complete |
| Output quality | **48 kHz**, against 24 kHz from both current engines |
| Licence | Apache-2.0, commercial use explicit |
| Peak memory | **5.60 GB** — against this M1's 5.73 GB Metal working set |
| Speed | **9x–126x real time**, median around 18x |

At roughly 18x real time a 45-second narration would take about 13 minutes, against 31 seconds
today. Combined with a 5.6 GB peak that nearly fills the Metal budget, it is not a practical
daily engine even setting the expressiveness question aside.

**Listen before you accept this.** My measures are pitch movement, loudness range and pace; they
cannot hear warmth, curiosity or intent. If you hear a consistent difference between these, tell
me and I will reopen it:

```
samples/expressive/voxcpm_neutral_s11.mp3     samples/expressive/voxcpm_curious_s11.mp3
samples/expressive/voxcpm_surprised_s11.mp3   samples/expressive/voxcpm_confident_s11.mp3
samples/expressive/voxcpm_playful_s11.mp3
```
Seeds `s22` and `s33` are there too — comparing seeds *within* one instruction is the honest
test, because that is the noise any real effect has to beat.

## Would a narration planner help?

Not for emotion, and I will not build one that emits labels nothing can act on — which is what
it would be today. A planner is only worth its memory if the engine responds to it, and none of
them does.

A planner **would** earn its place driving the things that demonstrably work, because Voice
Studio already controls them deterministically:

- where to split sections, at phrase rather than character boundaries;
- how long each pause should be, from the meaning of the break rather than its punctuation;
- per-section pace, which reference-tempo conditioning genuinely changes;
- which sentences deserve a second take from the other engine.

That is text analysis feeding timing controls, and it needs no new model at inference time — a
rules pass would cover most of it. It would not make Hal sound curious. It would make the
narration *phrase* better, which is a smaller and more honest claim.

Memory would allow it: a 0.5–1 B instruct model at 4-bit is roughly 0.4–0.8 GB and would run
**before** generation, then be released, so it never coexists with a TTS model.

## Answers

1. **Which models genuinely support expressive voice cloning?** None that I could verify.
   OmniVoice has the right architecture — instruction and reference in one prompt — and is
   non-commercial. VoxCPM2 is commercial and accepts both, but its instruction did not change
   delivery while cloning.
2. **Which run on this Mac?** Qwen3-TTS (3.84 GB peak), Chatterbox (4.51 GB), VoxCPM2 (5.60 GB,
   close to the limit). OmniVoice would be the lightest at 1.45 GB if its licence allowed it.
3. **Free and commercially usable?** Qwen3-TTS (Apache-2.0), Chatterbox (MIT), VoxCPM2
   (Apache-2.0). Not OmniVoice, Breeze-TTS-2 or F5-TTS.
4. **Can Hal's voice survive changing emotion?** His *voice* survives — VoxCPM2 held identity at
   0.91–0.95. The *emotion* did not change, so the question does not really arise yet.
5. **Would a planner help?** For pauses, phrasing and pace, yes. For emotion, no.
6. **Best balance today?** The engines you already have. Qwen3-TTS as the fast default,
   Chatterbox as the per-section alternative, chosen by ear.
7. **Limitations.** No local, commercially licensed model gives directed emotional delivery over
   a cloned voice. Expressive character still comes from the reference recording.
8. **What to integrate next?** Nothing new on this evidence. I am not proposing VoxCPM2: it is
   slower, heavier, and unproven on the one capability it was downloaded for.

## If you want to push further

The highest-value change is not a model at all — it is **the reference recording**. Cloning
reproduces the delivery of the sample. A reference of Hal sounding curious will produce curious
narration far more reliably than any instruction tested here. Multiple references per voice, one
per mood, selected per section, would use the mechanism that measurably works. That is a real
feature built on evidence, and it needs no new engine.

Say the word and I will scope it.

## Disk

`models/evaluation/VoxCPM2-8bit` is 3.23 GB, unwired. Earlier candidates remain beside it. Say
the word and I will remove any of them.
