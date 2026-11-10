# IndexTTS-2 feasibility — research only

24 October 2026. Nothing was downloaded, installed or integrated; Voice Studio, its engines, Hal, Mike, recordings, projects and model files are unchanged. Sources are official repositories and model cards unless marked third-party. This is not legal advice.

## Recommendation

**Do not adopt IndexTTS-2 now.** Three blockers, any one of which is enough:

1. **Licence:** the official inference pipeline requires a third-party semantic codec whose weights are **CC-BY-NC-4.0 (non-commercial)**. The bilibili licence that covers IndexTTS-2's own weights does not cover that file.
2. **Memory:** the official code runs fp32 on Apple Silicon, about **7.6–8.8 GB of weights** before macOS and the app, on an 8 GB M1.
3. **Delivery is not context-aware:** emotion is one 8-value vector per call, chosen manually or by a text classifier, and it has no category for curiosity or emphasis.

What it does well: in a small third-party benchmark it had the **best speaker similarity** of eight models, which matters for keeping Hal's voice.

If you want to keep pursuing this, the two cheapest next steps (each needs your approval):
- Email bilibili (indexspeech@bilibili.com) asking whether commercial voiceover use covers the MaskGCT codec, or whether IndexTTS-2.5's own `codec.pth` replaces it.
- Run a paper feasibility check of **CosyVoice 3** (Apache-2.0 weights), which appears to accept instruction plus reference voice in one call.

## 1. Licensing

| Component (all required at inference) | Weights licence | Source |
|---|---|---|
| IndexTTS-2 GPT, S2Mel, emotion matrices, Qwen 0.6B emotion model | **bilibili Model Use License Agreement** (covers "model weights and final code" published by bilibili) | GitHub `LICENSE`; HF card declares no licence field |
| Semantic codec, `amphion/MaskGCT` `semantic_codec/model.safetensors` | **CC-BY-NC-4.0**; trained on Emilia | MaskGCT model card |
| w2v-BERT 2.0 (`facebook/w2v-bert-2.0`) | MIT | model card |
| BigVGAN v2 22 kHz (`nvidia/bigvgan_v2_22khz_80band_256x`) | MIT | model card |
| CAMPPlus (`funasr/campplus`) | Apache-2.0 | model card |

**bilibili licence terms that matter to you:**
- Commercial use is allowed royalty-free unless you exceed **100 million monthly active users** or **RMB 1 billion annual revenue**; a YouTube channel is far below both.
- It prohibits using the model *or its outputs* to improve any other AI model, except non-commercial ones.
- You must keep its notices.
- High-risk uses are prohibited.
- The licence can be revoked on breach.
- It is governed by PRC law, with arbitration in Shanghai, and the **Chinese text prevails**.
- It has no voice-consent clause; responsibility for personality and privacy rights is yours.

**The blocker:**
- The official code always loads the semantic codec downloaded from `amphion/MaskGCT` (`model_download.py`, `infer_v2.py`). The loading code has no version-specific branch.
- That makes commercial voiceover generation with the official pipeline **not cleanly permitted**.
- IndexTTS-2.5 ships its own `codec.pth` under the bilibili licence, but in the current code the MaskGCT file is still the one loaded. I could not confirm what `codec.pth` is for. Only bilibili can settle this.

**Separate from IndexTTS:** Hal itself is an ElevenLabs voice. Its profile already notes that re-cloning rights are unverified, and that is true for any engine.

## 2. Voice cloning

- **Yes, it clones from a reference.** It takes `spk_audio_prompt`, a recording of the voice to clone; the code truncates it to 15 s.
- **Identity preservation is the strongest point I found.** A third-party benchmark (soniqo, ten English clips, chip not named, not a listening panel) measured speaker cosine **0.738**. That compares with Chatterbox 0.642, VoxCPM2 0.547 and Qwen3-TTS 1.7B 0.491.
- **Caveat:** the official README warns that random sampling "reduces the voice cloning fidelity".

## 3. Emotion control and context

**Manual control works with the cloned voice.** This is the design goal: the paper claims timbre and emotion are separated. Emotion is chosen in one of three ways, alongside the speaker reference:
- a separate emotion recording (`emo_audio_prompt`);
- an 8-value vector over happy, angry, sad, afraid, disgusted, melancholic, surprised and calm;
- a text description turned into that vector.

`emo_alpha` sets the strength.

**There is no automatic, context-aware delivery.** `use_emo_text` runs a fine-tuned Qwen 0.6B *text-emotion classifier*:
- It returns **one vector for the whole call**.
- That vector is applied to every segment of a long text (segments of about 120 tokens, joined with 200 ms of silence).
- It does not shape a question differently from a conclusion within a passage.
- It has no "curious", "explanatory" or emphasis category.

Per-sentence delivery would mean Voice Studio choosing a vector for each section, which is still manual or rule-based. The categories sit awkwardly for explainers: "surprised" is the closest to curiosity and "calm" to explanation. **Word emphasis is not supported.**

**Not verified here:** whether its emotion vectors move delivery by more than take-to-take variation while cloning *Hal*. That is the same test VoxCPM2 and the reference-clip idea both failed.

## 4–5. Hardware and performance

**Disk:**

| Path | Size | Made up of |
|---|---|---|
| Official PyTorch | **≈ 11.2 GB** | IndexTTS-2 repo 5.90 GB (GPT 3.48, S2Mel 1.20, Qwen emotion 1.19) + w2v-BERT snapshot 4.65 GB (whole repo, includes a duplicate checkpoint) + codec 0.18 + BigVGAN 0.45 + CAMPPlus 0.03 |
| Community MLX port (`mlx-indextts`) | **≈ 4.3 GB**, plus ~2.5 GB of upstream encoders fetched at runtime | fp32 weights; no Qwen emotion model |
| fp16 export (`aufklarer/IndexTTS2-MLX-fp16`) | 5.0 GB | Its card says "runtime support is not implied" |

**Memory:**
- The official code auto-selects Apple's GPU backend (MPS) but **forces fp32** there. Weights alone come to about 7.6 GB, or 8.8 GB with the emotion classifier. That exceeds the 8 GB of unified memory before macOS, so expect heavy swapping or failure.
- Half precision would roughly halve that. The only figure I found is a third-party peak of **2.9 GB** (fp16, chip not named), and that measure may under-count GPU memory.
- **Estimate for your M1:** feasible only on an fp16 MLX path, and about as tight as Chatterbox (4.4 GB today).

**Speed:**
- Official: RTF 0.33 on an RTX 4090 (CUDA).
- Apple Silicon: RTF ≈ 1.9 on an **M5 Max** in fp32 (Mandarin, mlx-indextts card), and 1.0 fp16 on an unnamed chip (soniqo).
- **Estimate for an M1 8 GB** (GPU several times slower than an M5 Max): roughly **5–15× real time**, similar to or slower than Chatterbox's ~10×. I found no M1 or M2 measurement.

**Quantisation:** no official quantised release. Quantising is allowed under the bilibili licence, where it counts as a derivative work; the codec licence still applies.

**IndexTTS-2.5** claims 2.28× faster generation (25 Hz codec, lighter decoder stage), is bilibili-licensed, and has the same codec question.

## 6. Offline use

Inference is local once every file is present. But:
- **Downloads on first run:** the official code fetches the four auxiliary models on first run, from ModelScope or a third-party mirror.
- **No offline guard:** it does not honour `HF_HUB_OFFLINE`, and any missing file triggers a network download.
- **Web UI downloads:** the web UI fetches example audio.

Running it offline would mean pre-populating its cache and verifying under the same network-deny sandbox Voice Studio's engines use.

## 7. Quality evidence

- **Paper (arXiv 2506.21619):** claims to beat other zero-shot models on word error rate, speaker similarity and emotional fidelity. The abstract has no figures, and it is the authors' own evaluation.
- **Third-party (soniqo; 10 English clips; regression metrics, not human ratings):**
  - Best speaker similarity (0.738).
  - Weaker word accuracy: 5.1% WER vs Chatterbox 1.2%, VoxCPM2 1.8% and Qwen3-TTS 2.4%.
  - Lower predicted naturalness: UTMOS 2.98 vs Qwen3-TTS 3.50.
- **Missing:** I found no credible independent evaluation of expressive **English narration**, long-form consistency, or pronunciation in explainer content. The official demo page exists but I could not retrieve it.

## 8. Alternatives (weights licences checked where possible)

| Model | Cloning + emotion together | Weights licence | Fits an 8 GB M1? | Verdict |
|---|---|---|---|---|
| **IndexTTS-2 / 2.5** | Yes (manual vector, emotion recording or text) | bilibili + **CC-BY-NC codec** | fp16 only, unofficial | Blocked on licence and memory |
| **CosyVoice 3 0.5B** (`Fun-CosyVoice3-0.5B-2512`) | `inference_instruct2` takes an instruction (emotion, speed, dialect) and a reference recording in one call | **Apache-2.0** | 0.5B, plausibly; Apple support unstated | **Most promising next paper check.** Must show instructions survive cloning, which VoxCPM2's did not |
| Chatterbox v3 (installed) | `exaggeration` only | MIT | Yes (4.4 GB) | Already measured: no reliable effect |
| VoxCPM2 (tested 21 Oct) | Instruction accepted | Apache-2.0 | Yes | Instruction did not change delivery while cloning |
| Step-Audio-EditX | Cloning + 14 emotions, 32 styles | Code Apache-2.0; **weights licence not stated** | **No**: CUDA, 12–16 GB | Not feasible |
| Fish Audio S2 / OpenAudio | Cloning | Reported non-commercial | — | Excluded |
| OmniVoice, F5-TTS, Spark-TTS | Cloning | Non-commercial | — | Excluded (earlier reports) |

None of these understands sentence meaning on its own. At best they accept a manual emotion or instruction per call, which Voice Studio would have to supply per section.

## Sources

Official: [index-tts GitHub](https://github.com/index-tts/index-tts) · [LICENSE](https://raw.githubusercontent.com/index-tts/index-tts/main/LICENSE) · [infer_v2.py](https://raw.githubusercontent.com/index-tts/index-tts/main/indextts/infer_v2.py) · [model_download.py](https://raw.githubusercontent.com/index-tts/index-tts/main/indextts/utils/model_download.py) · [IndexTeam/IndexTTS-2](https://huggingface.co/IndexTeam/IndexTTS-2) (file sizes via the HF API) · [IndexTeam/IndexTTS-2.5](https://huggingface.co/IndexTeam/IndexTTS-2.5) · [IndexTTS2 paper](https://arxiv.org/abs/2506.21619) · [IndexTTS 2.5 paper](https://arxiv.org/abs/2601.03888) · [amphion/MaskGCT](https://huggingface.co/amphion/MaskGCT) · [facebook/w2v-bert-2.0](https://huggingface.co/facebook/w2v-bert-2.0) · [nvidia/bigvgan_v2_22khz_80band_256x](https://huggingface.co/nvidia/bigvgan_v2_22khz_80band_256x) · [funasr/campplus](https://huggingface.co/funasr/campplus) · [Fun-CosyVoice3-0.5B](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512) · [Step-Audio-EditX](https://huggingface.co/stepfun-ai/Step-Audio-EditX)

Community and third-party: [mlx-community/IndexTTS-2-MLX](https://huggingface.co/mlx-community/IndexTTS-2-MLX) · [aufklarer/IndexTTS2-MLX-fp16](https://huggingface.co/aufklarer/IndexTTS2-MLX-fp16) · [soniqo voice-cloning benchmarks](https://soniqo.audio/blog/voice-cloning-benchmarks) · [bentoml open-source TTS overview](https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models) · [pinggy self-hosted TTS overview](https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models/)
