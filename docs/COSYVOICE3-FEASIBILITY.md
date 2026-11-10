# CosyVoice 3 (Fun-CosyVoice3-0.5B-2512) feasibility — research only

24 October 2026. Nothing was downloaded or installed; Voice Studio, its engines, Hal, Mike, recordings, projects and model files are unchanged. Sources are the official FunAudioLLM repository, code and model card unless marked third-party. This is not legal advice.

## Assessment

**Promising enough for a measured trial. Not proven to meet your goal.**

**It clears hurdles IndexTTS-2 failed:**
- Apache-2.0 weights and code.
- Permissive dependencies on macOS.
- A plausible fit in 8 GB.
- An architecture that genuinely separates *instruction* from *voice*.

**It falls short of your goal on paper:**
- The official instruction list has **no curious, surprised, confident or explanatory delivery**. It offers only happy, sad, angry, fast, slow, loud, soft, Chinese dialects and two novelty roles.
- The emotion and speed instructions are written in Chinese.
- Nothing official measures how well instructions are followed **while cloning a voice**.
- Official code has **no Apple-GPU path**, so on your Mac it runs on CPU.

Whether instructions work on *Hal*, in English, without losing Hal, is unknown and needs the experiment below.

## 1. Licence and dependencies

| Item | Licence | Source |
|---|---|---|
| Code (`FunAudioLLM/CosyVoice`) | Apache-2.0 | GitHub |
| Weights (`Fun-CosyVoice3-0.5B-2512`) | **Apache-2.0** in the model card metadata | Hugging Face |
| Python dependencies used on macOS (torch, torchaudio, transformers, onnxruntime CPU, librosa, openai-whisper, modelscope, diffusers, lightning…) | Permissive (BSD, MIT, Apache, ISC). Not yet checked: conformer, pyworld, wetext, wget | `requirements.txt` |
| TensorRT, deepspeed, onnxruntime-gpu | NVIDIA proprietary or GPU-only, **Linux-only** markers | Not installed on a Mac and not needed |

The model card's line "for academic purposes only" refers to its demonstration content. The weights licence is Apache-2.0 and is not restricted by it. Unlike IndexTTS-2, no non-commercial component appears in the inference path: the speaker encoder, speech tokenizer, flow model and vocoder all ship in the same Apache-2.0 repository.

## 2. Voice cloning

- **`inference_zero_shot(text, prompt_text, prompt_wav)`** is ordinary reference cloning, with the reference's transcript, like Qwen3's.
- **Official figures** (English test-en):

  | | Speaker similarity | Word error rate |
  |---|---|---|
  | Human | 73.4 | 2.14% |
  | CosyVoice 3 base | 71.8 | 2.24% |
  | CosyVoice 3 RL variant | 69.5 | 1.68% |

  These are the developers' own figures on their benchmark, not on Hal.
- **Pronunciation:** CMU phonemes can be written inline to fix a word. That is a cleaner override than respelling.

## 3. Does instruction work *together with* cloning? (read from the code)

`inference_instruct2(tts_text, instruct_text, prompt_wav)` → `frontend_instruct2`:

- **Kept from your reference recording:** the speaker embedding, the reference's speech tokens and its acoustic features. These feed the **flow-matching and vocoder stage**, which renders **timbre**.
- **Removed:** the reference's speech tokens on the **language-model stage**, which decides the speech tokens, so rhythm and delivery. The instruction text takes the place of the reference transcript.

So unlike Qwen3's cloning path, where the reference sits in the same stream as any instruction and wins, the reference is deliberately kept away from the stage the instruction steers. **Structurally, instruction and cloning can coexist.** That is the most important finding of this investigation, and it is a mechanism, not a measurement.

The expected cost follows from the same design. In instruct mode the language model no longer hears how Hal *speaks*: his rhythm, pitch habits and accent. Only his timbre survives, through the flow stage. Instructed takes may sound like Hal's voice with someone else's delivery. That needs to be heard.

## 4. What instructions exist

**Official `instruct_list`** (`cosyvoice/utils/common.py`), each written as `You are a helpful assistant. <instruction><|endofprompt|>`:

| Kind | Instructions | Language of the instruction |
|---|---|---|
| Emotion | very happy, very sad, very angry | Chinese |
| Speed | as fast as possible, as slow as possible | Chinese |
| Volume | as loudly as possible, very soft voice | **English** |
| Dialect | 17 Chinese dialects | Chinese |
| Role | Peppa Pig style; "answer like a robot" | Chinese |

- **Curiosity, surprise, confidence, explanation, emphasis:** not in the list. The language-model backbone is a Qwen 0.5B, so a free-form English instruction such as "Speak with curiosity" will be *accepted*, but nothing official shows it is *followed*. It must be measured.
- **Inline tags:** the tokenizer contains `<strong>…</strong>` (emphasis), `[breath]`, `[laughter]`, `<laughter>…</laughter>`, `[sigh]` and others. The only CosyVoice 3 example uses `[breath]` on Chinese text. `<strong>` comes from CosyVoice 2's fine-grained control, and I found no evidence that CosyVoice 3 honours it in English.
- **Independent listener evidence:** one third-party paper (EmoInstruct-TTS, arXiv 2606.20650; 20 raters) scored CosyVoice 3 at 3.44–3.98 out of 5 for emotion similarity and 4.34–4.55 for speaker similarity, with 1.97% WER. It does not say whether instructions or emotional reference audio were used, nor the language. **Weak evidence**, and possibly Chinese.

## 5. Could Voice Studio choose a delivery per sentence?

- **Choosing is feasible locally and offline.** Simple rules (a question mark gives "curious"; a sentence opening "So no," gives "confident conclusion") or a small local classifier could tag each section.
- **Following is the open question.** It needs CosyVoice 3 to follow *English, non-listed* instructions while cloning, which is unverified (§4).
- **Consistency risk:** each section is generated separately, and in instruct mode the reference's delivery is not anchored. Changing the instruction per sentence risks sections sounding like different performances. The Review tab would show that as pitch and brightness jumps between sections.
- **Model limits:** CosyVoice 3, like IndexTTS-2, takes one instruction per call and does not read sentence meaning by itself. "Context-aware" would be Voice Studio's rules, not the model's understanding.

## 6. Mac M1, 8 GB, offline, speed

- **Apple GPU:** none. The official code checks only for CUDA, otherwise runs on **CPU**. It forces fp16 off without CUDA. The ONNX parts run on the CPU provider.
- **Separate environment:** the code pins Python 3.10 and torch 2.3.1, so it would need its own environment and process. That fits Voice Studio's one-engine-per-process design.
- **No community Apple-native port found:** none in the installed mlx-audio, and none I could locate.

**Disk:** a minimal runtime set is ≈ 5.4 GB:

| File | Size |
|---|---|
| `llm.pt` (or `llm.rl.pt`) | 2.02 GB |
| `flow.pt` | 1.33 GB |
| `speech_tokenizer_v3.onnx` | 0.97 GB |
| Qwen `CosyVoice-BlankEN` | 0.99 GB |
| `hift.pt` + `campplus.onnx` | 0.11 GB |

The full repository snapshot is 9.75 GB with duplicates. A separate Python environment adds a few GB more.

**Memory (estimate):** about **4.5–6 GB** peak, all fp32. Similar to Chatterbox today (4.4 GB), so workable but tight on this Mac, which already swaps heavily.

**Speed (estimate, no M1 measurement found):** CPU-only, a 0.5B language model plus a 10-step flow decoder. My rough estimate is **1–4× real time**. That would sit between Qwen3 (≈1.3×) and Chatterbox (≈10×). Treat it as a guess until measured.

**Offline:** inference is local once the files are present. It must still be verified under Voice Studio's network-deny sandbox, because wetext and modelscope may fetch resources on first use.

## 7. Compared with the installed engines

| | Qwen3-TTS 0.6B (default) | Chatterbox v3 | CosyVoice 3 0.5B (on paper) |
|---|---|---|---|
| Weights licence | Apache-2.0 | MIT | Apache-2.0 |
| Runs on the Mac's GPU | Yes (MLX) | Yes (MLX) | **No, CPU only** |
| Speed on this M1 | ≈1.3× real time | ≈10× | ≈1–4× (estimate) |
| Peak memory | 3.6–3.8 GB | 4.4 GB | ≈4.5–6 GB (estimate) |
| Delivery control while cloning | None (reference overrides) | `exaggeration`, measured unreliable | **Instruction kept away from the voice reference** (structural); listed set lacks curious, surprised, confident |
| Copies Hal's speaking style | Yes (that is why it cannot be directed) | Yes | Not in instruct mode, by design |
| Emphasis | No | No | `<strong>` token exists; English use unverified |
| English speaker similarity / WER (developers' figures) | — | — | 71.8 / 2.24% |
| Output rate | 24 kHz | 24 kHz | 24 kHz in the config (not checked in code) |

## 8. Proposed next phase (needs your approval)

**What to download:** the ≈ 5.4 GB minimal set, into `models/evaluation/`, plus a separate Python 3.10 environment, with no change to the app. Optionally the RL variant (+2 GB).

**What to generate:** Hal's reference × three sentence types (question, explanation, conclusion) × five seeds, under these settings:
- zero-shot cloning (no instruction), as a baseline;
- `instruct2` with official instructions: happy, slow;
- `instruct2` with free-form English: "speak with curiosity", "speak confidently", "explain clearly";
- `instruct2` with `<strong>` on one word.

**What to measure:**
- whether each instruction moves pitch range, rate or loudness by more than the seed-to-seed spread (the same test VoxCPM2 and the reference-clip idea failed);
- speaker similarity to Hal, zero-shot vs instruct;
- word accuracy;
- generation speed and peak memory on this Mac.

All on the network-deny sandbox, with a listening page so you judge by ear.

**Stop condition:** if instructions do not separate from seed noise, or Hal is no longer recognisable in instruct mode, CosyVoice 3 is not worth integrating.

## Sources

Official:
- [CosyVoice GitHub](https://github.com/FunAudioLLM/CosyVoice)
- [cosyvoice.py](https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/cosyvoice/cli/cosyvoice.py)
- [frontend.py](https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/cosyvoice/cli/frontend.py)
- [example.py](https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/example.py)
- [common.py (instruct_list)](https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/cosyvoice/utils/common.py)
- [tokenizer.py](https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/cosyvoice/tokenizer/tokenizer.py)
- [requirements.txt](https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/requirements.txt)
- [Fun-CosyVoice3-0.5B-2512 model card](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512) (file sizes via the HF API)
- [CosyVoice 3 paper](https://arxiv.org/abs/2505.17589)

Third-party:
- [EmoInstruct-TTS (arXiv 2606.20650)](https://arxiv.org/html/2606.20650v1)
- [mlx-audio](https://sourceforge.net/projects/mlx-audio.mirror/)
