# Voice quality analysis — 20–21 October 2026

## Executive summary

I independently decoded **all 19 unique MP3s** referenced by [engine-comparison.html](engine-comparison.html): five Qwen/Chatterbox pairs and nine Chatterbox exaggeration/seed takes. Every file exists, is 24 kHz mono, and has no samples at digital clipping level. The clearest measurable difference is at the ends: the five Qwen clips have only **0.01–0.07 s** below −45 dBFS after the last active 10 ms frame, versus **0.37–0.53 s** for the five Chatterbox pairs. This warrants listening, especially to “The mystery is over.” It does **not** prove a missing final consonant or an unnatural ending.

**21 October update:** Metal is still inaccessible in this execution session, but a lightweight CPU fallback successfully transcribed all 19 clips using the project's existing Whisper weights, installed PyTorch code, and tokenizer. After expanding contractions and treating `realize`/`realise` as the same spelling, Qwen's five transcripts match all **69/69** scripted words; Chatterbox matches **67/69**, with two *ASR-detected substitutions* requiring listening confirmation. Across the five scripted pairs, ASR found no omitted or repeated words. Whisper recognizes the requested final words “together” and “over” in both engines. These results do **not** establish phonetic correctness, accent, naturalness, or emotional delivery. I cannot directly hear the recordings in this environment. No cloud service, model download, regeneration, or expensive benchmark was used.

## Offline transcription method and word findings — 21 October

Importing `mlx.core` still raises `ImportError: No Metal device available`; PyTorch reports CPU available and MPS unavailable. The installed `mlx_whisper/torch_whisper.py` model has matching weights after an in-memory mapping of MLX layer names and two convolution weight transposes. I used the package's own tokenizer and mel filters, 6-second input windows (all clips are under 5 seconds), English greedy decoding, and the existing 137 MB `models/whisper-base/weights.npz`. This one-off CPU path did not modify Voice Studio. The full 19-file batch took about **9.3 s** including model load; each inference took **0.27–0.55 s**. It is a faithful structural reuse of the weights, but its short-context greedy decoding has not been cross-checked against MLX output on an interactive Mac desktop.

| A/B script | Qwen ASR | Chatterbox ASR | Interpretation |
| --- | --- | --- | --- |
| 1. Question | Exact words, including “Have” and “together” | Exact words, including “Have” and “together” | No ASR mismatch. |
| 2. Surprise | Exact words | “they're” twice for scripted “they are” | Contraction normalization gives exact word agreement; this alone does not prove the spoken wording was contracted. |
| 3. Explanation | Exact words, opening “Flies” | **“Vies”** for opening **“Flies”** | ASR mismatch. A focused first-2.2-second recheck returned “Vise” for Chatterbox and “flies” for Qwen, raising concern about Chatterbox's opening /fl/ articulation. Actual phonemes remain unconfirmed. |
| 4. Emphasis | “realize” and “you're” for scripted “realise” and “you are” | “realize” and **“you were there”** for scripted “realise” and **“you are there”** | Spelling is equivalent and “you're” expands to “you are.” “Were” is a potential Chatterbox substitution; a focused final-2.24-second recheck also returned “you were there.” |
| 5. Conclusion | Exact words, including “So” and “over” | Exact words, including “So” and “over” | No ASR mismatch; final phoneme and cadence still require listening. |

All nine Chatterbox exaggeration/seed takes transcribe as **“Have you ever wondered why flies rub their hands together?”**, with “Have” and “together” present each time. The HTML does not print their intended prompt, so this establishes transcription consistency across takes, not exact-script compliance. The first and last words in every A/B clip are recognized except the opening “Flies” in Chatterbox's explanation; “there,” “food,” “themselves,” “together,” and “over” appear at the ends as expected. In the five scripted pairs, no additional or repeated words appear after normalization.

For the two discrepancies and the requested endings, a CPU adaptation of Whisper's cross-attention alignment gives **approximate listening windows**, not acoustically verified phoneme boundaries:

| Clip and word | Approximate window (s) | What is established |
| --- | --- | --- |
| Chatterbox explanation, scripted “Flies” → ASR “Vies” | **0.04–0.34** | Opening word is the repeated ASR discrepancy; aligner starts at 0.00 because it absorbs a little lead-in. |
| Chatterbox emphasis, scripted “are” → ASR “were” | **3.70–3.82** | Repeated ASR substitution signal; word boundary is uncertain at this short duration. |
| Qwen / Chatterbox question, “together” | **2.60–3.00 / 2.40–2.85** | Both recognized; final consonant completeness is unverified. |
| Qwen / Chatterbox conclusion, “over” | **4.60–4.95 / 3.70–4.20** | Both recognized; Chatterbox alignment reaches slightly into its quiet decay. Natural release is unverified. |

**Confirmed transcription findings** are the output differences above. **Suspected speech problems** are Chatterbox's opening /fl/ clarity and possible “were” substitution. Neither is a confirmed pronunciation error without an independent listen. Whisper recognition of “over” does not prove that the final /r/ (if rhotic in Mike's accent) or the ending cadence is intact.

## Inventory and measurements

The paths below are relative to `samples/engines/level-matched/`. Values are decoded MP3 durations and approximate quiet tail lengths (10 ms RMS frames below −45 dBFS). The five expected scripts are printed in the HTML and are used as the listening reference.

| Script | Qwen file · duration / tail (s) | Chatterbox file · duration / tail (s) |
| --- | --- | --- |
| Curious question: “Have you ever wondered why flies rub their hands together?” | `current_1-question.mp3` · 3.04 / 0.01 | `chatterbox_1-question.mp3` · 3.40 / 0.53 |
| Surprising fact: “Surprisingly, they are not plotting anything. They are cleaning themselves.” | `current_2-surprise.mp3` · 4.40 / 0.02 | `chatterbox_2-surprise.mp3` · 4.36 / 0.37 |
| Explanation: “Flies taste with their feet, so keeping them clean is how they find food.” | `current_3-explain.mp3` · 4.32 / 0.05 | `chatterbox_3-explain.mp3` · 3.84 / 0.42 |
| Emphasis: “You walk into a room and realise you have absolutely no idea why you are there.” | `current_4-emphasis.mp3` · 4.16 / 0.07 | `chatterbox_4-emphasis.mp3` · 4.64 / 0.51 |
| Conclusion: “So the next time you see it, you will know exactly what is going on. The mystery is over.” | `current_5-conclusion.mp3` · 4.96 / 0.06 | `chatterbox_5-conclusion.mp3` · 4.52 / 0.43 |

| Exaggeration | Seed 11 file · duration / tail (s) | Seed 22 file · duration / tail (s) | Seed 33 file · duration / tail (s) |
| --- | --- | --- | --- |
| 0.25 | `chatterbox_exag25_s11.mp3` · 3.00 / 0.38 | `chatterbox_exag25_s22.mp3` · 3.08 / 0.48 | `chatterbox_exag25_s33.mp3` · 3.12 / 0.48 |
| 0.60 | `chatterbox_exag60_s11.mp3` · 2.88 / 0.50 | `chatterbox_exag60_s22.mp3` · 3.12 / 0.39 | `chatterbox_exag60_s33.mp3` · 2.92 / 0.53 |
| 1.00 | `chatterbox_exag100_s11.mp3` · 2.88 / 0.61 | `chatterbox_exag100_s22.mp3` · 3.44 / 0.67 | `chatterbox_exag100_s33.mp3` · 2.80 / 0.42 |

The quiet-tail estimate depends on the −45 dBFS threshold; it is a timing measure, not a phonetic label. The original WAVs for `current_1-question`, `current_5-conclusion`, and `chatterbox_5-conclusion` show essentially the same endings, so MP3 encoding and level matching did not introduce the tail difference in those clips. There is no sample clipping in any referenced MP3. These comparison clips are individual engine outputs; Voice Studio's assembled narration path separately adds **0.32 s** of final room (`styles.TAIL_ROOM`), so the clip tails do not establish that exported narrations end the same way.

## Priority speech and ending audit

**Verified pronunciation issues:** none can be named with confidence. CPU ASR and approximate word alignment now ran, revealing the two Chatterbox discrepancies above, but neither can distinguish a mispronunciation from a recognition error. Waveform energy and ASR agreement cannot verify syllables or final consonants. The first and last words of every take still need a script-guided listen. The nine exaggeration takes need their intended prompt printed before exact-script compliance can be established.

The conclusion has an approximately **0.20 s** low-energy gap at **3.83–4.03 s** in Qwen and **0.28 s** at **2.70–2.98 s** in Chatterbox, plausibly before the final sentence. Active audio then continues to approximately **4.90 s** and **4.09 s**, respectively. Qwen's last 20 ms are essentially silent; Chatterbox has about **0.43 s** of quiet tail. These data do not show an abrupt digital cut at the file boundary in either conclusion. They also cannot establish whether “over” contains its full final sound or whether the cadence feels finished. Qwen's question clip deserves the same check: its last 20 ms still contain energy near **−40 dBFS**, and it has virtually no quiet tail, though its original WAV falls in level toward the end rather than showing an obvious boundary click.

For a focused listening pass, compare these windows in the [HTML player](engine-comparison.html):

| Priority | Window and listening question |
| --- | --- |
| First and last words | Each complete A/B clip: check exact words, syllables, final consonants, and whether onset or release is swallowed. |
| Question | Both `1-question` clips, especially the final ~0.6 s: does “together” finish and does the question sound curious? |
| Surprise and explanation | Both `2-surprise` and `3-explain` clips: is “Surprisingly” clear, does the fact receive appropriate stress, and are the pauses conversational? |
| Emphasis | Both `4-emphasis` clips: does “absolutely no idea” carry meaningful emphasis rather than only louder or higher pitch? |
| Ending | Qwen `5-conclusion` **3.83–4.96 s**; Chatterbox **2.70–4.52 s**: check the whole final sentence, especially the vowel and final consonant of “over,” vocal decay, and whether the sentence feels complete. |
| Exaggeration | Compare 0.25 → 0.60 → 1.00 **within each seed**, then compare seeds at each level. Check intended emotion, intelligibility, and whether Mike's voice remains recognizable. |

If a word sounds wrong, record the **file, word, start/end time, expected pronunciation, and what was actually heard**. The ASR alignment above narrows the priority windows, but listening must confirm the phoneme. Do not infer a missing /r/ or extend “over” just because the Qwen file has a short tail.

## Accent, naturalness, context, and voice identity

The Mike reference is present at `local_data/voices/9b4dfa46251849558cbc7dd6fea32283/baa485815ba04490926bf7d66253afc6/reference.wav` (12.34 s). An accent or identity comparison requires listening to that reference beside the generated clips. I cannot classify either engine as American, British, or another English variety, identify accent shifts, or say which retains Mike's accent. The spelling “realise” in the fourth script is not acoustic evidence of a British accent.

The durations and gaps above show timing differences but cannot tell whether the question conveys curiosity, the fact sounds surprising, the explanation sounds conversational, the emphasis fits the meaning, or the conclusion feels natural. Pitch movement or loudness range alone would not settle those questions. I therefore make no claim that either engine sounds more human, has more appropriate intonation, or preserves voice identity better.

## Chatterbox exaggeration: independent acoustic check

Across the nine takes, an RMS loudness-dynamics proxy (90th minus 10th percentile of active 10 ms frames) averaged **19.0, 19.7, and 21.4 dB** at exaggeration 0.25, 0.60, and 1.00. The individual values overlap: **17.5–20.5**, **17.4–22.9**, and **19.2–23.3 dB**. At seed 11 the metric goes **19.1 → 17.4 → 19.2 dB**, so it is not consistently monotonic. Estimated active duration averages about **2.56, 2.44, and 2.42 s**, with seed variation up to about **0.39 s** at level 1.00. The setting may change amplitude dynamics, but this small matrix does not establish a repeatable improvement in expression, pronunciation, or identity. This is an independent measurement of the referenced audio, not a reuse of the earlier pitch analysis.

## Engine comparison and recommendation

The requested 1–10 scores are withheld because no category below has sufficient perceptual or word-level evidence for a defensible quality score.

| Category | Qwen | Chatterbox | Evidence / remaining check |
| --- | --- | --- | --- |
| Pronunciation accuracy | — | — | CPU ASR: 69/69 scripted words for Qwen versus 67/69 for Chatterbox; the two Chatterbox substitutions need listening confirmation. |
| Accent consistency | — | — | Needs listening against Mike's reference. |
| Naturalness and vocal artifacts | — | — | No clipping detected; other artifacts and human realism require listening. |
| Emotional expression | — | — | Acoustic dynamics are inconclusive. |
| Context-aware intonation | — | — | Needs the five prompt-specific listening checks above. |
| Emphasis | — | — | “Absolutely no idea” has no word-level perceptual assessment. |
| Pacing | — | — | Durations differ; appropriateness requires listening. |
| Sentence endings | — | — | Qwen tails are shorter; phonetic completeness and naturalness unresolved. |
| Voice identity preservation | — | — | Mike reference exists but was not audibly compared. |

**Answers to the decision questions:** Qwen has stronger **ASR text agreement**, but the most accurate *pronunciation*, most consistent American accent (if either has one), most natural voice, better questions/emphasis, and more complete *spoken* endings are **undetermined**. Chatterbox's exaggeration control changes one measured acoustic proxy but has **not been shown to improve expression**. On present quality evidence, integration is **not justified yet**. The existing generation logs (`engine-current.json`, `engine-chatterbox.json`) report **29.1 s / 3.843 GB** for Qwen versus **187.9 s / 4.512 GB** for Chatterbox over the same five lines; these are prior performance measurements, not a new benchmark or proof of quality.

For the current engine, first audit the exact final phonemes in the question and conclusion and check an assembled export; compare generated WAVs with any earlier raw stage if a defect is heard. If a word is missing, regenerate or adjust the phrasing of that section and verify the script. If the word is complete but the assembled ending still feels cramped, review the existing trailing-room setting. Do not lengthen final letters mechanically: silence cannot restore a missing consonant. Keep an exact-script ASR plus manual listening gate for future A/B evaluations, and print the experiment sentence beside the nine exaggeration players. **No application, model, profile, or original audio was changed.**

**Confidence:** high for inventory, decode integrity, duration, clipping, and threshold-based tail timing; moderate for the two reproducible **ASR outputs** and approximate attention-derived word windows; insufficient for actual phonetic accuracy, accent, naturalness, emotional delivery, or engine quality ranking.
