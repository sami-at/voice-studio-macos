# CosyVoice 3 (0.5B) controlled evaluation — stopped at the memory stop condition

24 October 2026. MacBook M1, 8 GB. Not integrated. Voice Studio, Qwen3, Chatterbox, Hal, Mike, narrations and settings are untouched (Hal's reference was only read).

## Result

**Stopped after one take, under the stop conditions you set:**
- CosyVoice 3 **cannot run reliably within 8 GB** on this Mac.
- One 5-second sentence pushed the process to an **8.63 GB peak memory footprint**.
- macOS swapped out **~880,000 pages (≈14 GB)** while generating it.
- It took **148 s for 5.0 s of audio (29.6× real time)**, against ≈1.3× for Qwen3 and ≈10× for Chatterbox.

The planned 110-take instruction test was therefore **not run**. **Nothing below says anything about instruction-following**, because no instructed take was generated.

**Recommendation: do not pursue CosyVoice 3 on this Mac.** The official implementation has no Apple-GPU path (it runs on CPU in fp32), and that is what makes it both too big and too slow here. Making it fit would mean unofficial porting work (a half-precision or MPS/MLX conversion). That is a separate engineering project with no guarantee of success. I have not started it.

## Setup (all under `models/evaluation/cosyvoice3/`)

| Item | Detail |
|---|---|
| Source | Official `FunAudioLLM/CosyVoice`, commit `074ca6d` (26 May 2026), code only |
| Environment | Isolated venv (Homebrew Python 3.11), CPU-only PyTorch 2.3.1, pinned versions from the official `requirements.txt`. **No CUDA, TensorRT, deepspeed or GPU packages.** 1.4 GB |
| Weights | Minimal runtime set from `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`, 5.1 GB. Sizes match the official listing byte for byte: LLM 2.02 GB, flow 1.33 GB, speech tokenizer 0.97 GB, Qwen backbone 0.99 GB, vocoder 0.08 GB, speaker encoder 0.03 GB. The RL variant, duplicate tokenizer and TensorRT files were not downloaded |
| Extra packages needed beyond the obvious | hydra-core, lightning, pyarrow, rich, matplotlib, pyworld, gdown, wget, librosa. All are official pins with permissive licences; the config loader imports training-time code even for inference |
| Disk | 14 GB free at the start; never fell below 11 GB |

## Offline use

- **Generation ran to completion inside Voice Studio's network-deny sandbox**, so inference is local.
- **Text normalisation does not work offline as shipped.** The default normaliser (`wetext`) downloads its rules from ModelScope on first use. Here ModelScope refused without an account token (HTTP 403, rate-limited), and offline CosyVoice falls back to "no frontend", meaning numbers, symbols and abbreviations are not normalised.
- The test sentence contains none of those, so it was unaffected. A script with "2026", "Dr." or "%" would be.

## Objective measurements: one sentence, one seed (indicative only)

"Have you ever wondered why do flies rub their hands together like they're planning something?", Hal reference, seed 42. These are single takes, so differences between engines are within what a different seed can produce.

| | ElevenLabs | Qwen3 | Chatterbox | CosyVoice 3 |
|---|---:|---:|---:|---:|
| Words correct (offline Whisper) | ✓ | ✓ | ✓ | ✓ |
| Identity to Hal: CAMPPlus (CosyVoice's own encoder; may favour it) | 0.905 | 0.915 | 0.892 | 0.932 |
| Identity to Hal: spectral voice-print (engine-neutral, crude) | 0.968 | 0.923 | 0.929 | 0.936 |
| Median pitch (Hal's reference: 141 Hz) | 160 Hz | 170 Hz | 120 Hz | 128 Hz |
| Pitch range | 21.5 st | 16.9 st | 19.5 st | 16.9 st |
| 6.3 kHz octave relative to 1 kHz (upper-range detail) | **−3.1 dB** | −14.2 | −18.0 | −15.4 |
| 9 kHz octave relative to 1 kHz | **−4.5 dB** | −15.9 | −18.5 | −16.2 |
| Review flags | — | — | — | abrupt start |
| Generation time for this sentence | — | ≈6 s | ≈50 s | **148 s** |

What the numbers suggest, without proving it:
- CosyVoice may keep Hal's identity at least as well as the current engines.
- It does **not** fix the clarity gap. Its upper range is as dull as Qwen3's, 11–12 dB below ElevenLabs at 6–9 kHz.
- The abrupt-start flag is one take and may be seed luck.

## Not measured (because of the stop)

- Instruction-following against seed noise (official happy and slow; free-form curious, confident, concluding).
- Emphasis tags.
- Instruct-mode identity.
- Five-seed distributions.
- Chatterbox runs of the same sentences.

These remain open questions, not negative results. The structural reason instructions *could* work while cloning (`docs/COSYVOICE3-FEASIBILITY.md` §3) is unchanged.

## Subjective listening

Open `samples/cosyvoice3-eval/index.html`: the same sentence from ElevenLabs, Qwen3, Chatterbox and CosyVoice 3, level-matched to −24 LUFS, with a blind mode. **I have not listened**; the judgement is yours. One sentence cannot rank engines.

## What is left on disk, and how to remove it

`models/evaluation/cosyvoice3/` holds about 6.5 GB: weights 5.1 GB, environment 1.4 GB, source 8 MB, outputs and logs. Nothing in Voice Studio references it. Deleting that folder removes everything; I have not deleted it in case you want the probe re-run with other apps closed.

## Options, each needing your approval

1. **Delete the evaluation folder** (recommended if you accept this result).
2. **Re-run the probe once with other apps (browsers, VS Code) closed.** This would show whether the 8.6 GB footprint and 30× speed are partly caused by the machine already carrying about 20 GB of swap. I expect it would still exceed what is practical, because the fp32 weights alone are about 5 GB.
3. **Attempt an unofficial half-precision or MPS port.** This is real engineering effort with an uncertain outcome. Only worth it if you want to keep chasing instruction control specifically.
