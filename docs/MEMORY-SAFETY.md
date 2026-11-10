# Memory safety for model evaluations (8 GB M1)

Written after the 24 October watchdog panic (`docs/INCIDENT-2026-10-24-RESTART.md`). **This reduces risk; it cannot guarantee that a kernel panic will not happen.** Memory can be allocated faster than the guard samples it, other apps or the kernel can exhaust memory on their own, and a watchdog panic can follow from paging pressure the guard never sees.

## The guard: `scripts/eval_guard.py`

It uses the standard library and built-in macOS tools only, loads no model, and is not used by the Voice Studio app. Wrap every evaluation that loads a model:

```
python scripts/eval_guard.py --weights-gb 2.0 --kind mlx-quantized -- <evaluation command>
python scripts/eval_guard.py --check --weights-gb 5.1 --kind fp32-cpu      # pre-flight only
```

**Before starting it refuses if:**
- a kernel panic report is newer than your last `--acknowledge-panic`;
- a previous guarded run was interrupted (cleared only by `--clear-interrupted`);
- memory free (`kern.memorystatus_level`) is below 40 %;
- swap in use is above 10 GB;
- disk free is below 25 GB;
- Google Chrome is running;
- another model or TTS process is running;
- the estimated peak footprint is above 4.5 GB.

**Peak estimate:** weights on disk × 1.9 (MLX quantised), × 1.8 (MLX fp16) or × 1.7 (fp32 on CPU). These factors were measured on this Mac:

| Model | On disk | Measured peak |
|---|---:|---:|
| Qwen3 | 2.0 GB | 3.8 GB |
| Chatterbox | 2.5 GB | 4.4 GB |
| CosyVoice 3 | 5.1 GB | 8.6 GB |

**While running:** the command runs in its own process group, and the guard samples once a second, starting before the model loads:
- memory of the whole process tree (RSS every second, physical footprint including compressed memory every 5 s);
- system memory free;
- swap growth;
- disk free.

It terminates the whole group (SIGTERM, then SIGKILL after 3 s) when any of these happens:
- the evaluation uses more than 5 GB;
- system memory free falls below 12 %;
- swap grows more than 1.5 GB within a minute;
- disk free falls below 10 GB.

**Never restarts.** A stopped or crashed run leaves `~/.voice_studio_eval_guard/running.json` with the reason. The next run is refused until a person reads it and clears it.

**Tests:** `tests/test_eval_guard.py`, 19 tests. They use fake readings and a harmless `sleep` child only; no model and no memory load.

## Limits for experiments with unproven models on this Mac (not everyday generation)

- **One model at a time, with an estimated peak of 4.5 GB or less.**
  - Qwen3 (3.8 GB) fits.
  - Chatterbox (4.4 GB) is at the limit, so close Chrome.
  - CosyVoice 3, the official IndexTTS-2 and Qwen3-TTS 1.7B do not fit.
- **Restart the Mac** if swap at idle is above 10 GB. It has been 8–20 GB, mostly the browser session.
- **Keep at least 25 GB of disk free.** Swap files grow on the system disk.
- **After any interrupted heavy run**, look for a new `panic-full-*.panic` in `/Library/Logs/DiagnosticReports` (and `Retired/`) before trying again. The guard does this check automatically.

## Everyday generation inside Voice Studio (`voice_studio/resources.py`)

Separate from, and less strict than, the experiment guard: it is calibrated for the two installed engines, whose peaks were measured here. You do not need to close Chrome, Safari or VS Code. Voice Studio never closes, suspends, reprioritises or otherwise touches another application, never changes system settings, and asks for no administrator access. macOS keeps managing inactive memory through its normal compression and swap.

**Mechanisms that are actually used:**

1. **Process isolation.** Every generation runs in its own worker process. When it ends, for any reason, macOS reclaims all of its memory, including the MLX/Metal buffers that hold the model. Idle Voice Studio measured **153 MB** with no worker running.
2. **Admission before any model loads.** This runs in the window before the worker starts, and again inside the worker before every load, including after an engine switch, once the previous engine has been released. It reads:
   - available memory (`kern.memorystatus_level`);
   - swap growth over the last minute;
   - disk free;
   - other generation workers;
   - a recent panic report you have not reviewed.

   | Situation | What happens |
   |---|---|
   | Qwen3 with at least 22 % available, Chatterbox with at least 28 % | Starts |
   | Below that (or below the 12 % floor), swap growing over 1 GB a minute, or disk under 12 GB | **Waits** |
   | Another worker running, disk under 6 GB, or an unreviewed panic from the last 72 h | **Refuses** |

   The thresholds are set from earlier runs on this Mac, which completed at 30–37 % available with Chrome open.
3. **Waiting state.** The message is "Waiting for enough available memory… Your applications and projects are untouched." There are **Retry now** and **Stop waiting** buttons. It re-checks automatically every 10 s for at most 5 minutes. Only readings are taken while waiting; no model is ever loaded.
4. **Live monitoring, quiet unless it matters.** Readings are taken off the interface thread every 1.5 s: available memory, swap, disk, and the worker's physical footprint plus MLX's own counter. Readings and decisions go to the job log (`local_data/logs/<job>.log`), not to the screen.

   **Swap growth alone is not treated as danger.** Loading a model makes macOS compress and swap other apps' idle memory for a few seconds. On 25 October this one-off displacement, about 1.4 GB in under 30 s and computed from a too-short window, was read as "2.8 GB a minute". It stopped three runs that were healthy: sections were generating in seconds, no jetsam or panic was reported, and 36–41 % of memory was available. Growth is now measured only over at least 45 s of readings.

   - **Pause** (finish the section, release the model, continue automatically) when available memory stays below 10 % for 15 s, or is below 15 % while swap grows more than 3 GB a minute over a full window. Voice Studio then waits (re-checking every 10 s, up to 5 minutes) and resumes only the unfinished sections. One Generate press can resume itself up to 6 times.
   - **Emergency stop** (terminate the worker, keep finished sections, explain, never restart on its own) when available memory is below 5 % on two readings in a row, below 8 % with swap growing more than 6 GB a minute, disk falls under 4 GB, or the worker passes 5 GB (Qwen3) or 6 GB (Chatterbox).
3b. **What you see:** "Generating section X of Y", the overall progress for the whole narration, Cancel, then "Generation complete." A message appears only when generation is paused or needs you.
5. **One engine at a time.** Consecutive sections reuse the loaded engine. Switching releases the first engine (`gc` plus `mx.clear_cache`) before the resource check and the next load.

**Not done, deliberately:**
- **Raising the worker's priority or QoS class.** It cannot create memory, and its benefit could not be shown without heavy runs; the worker keeps its normal inherited priority.
- **Capping MLX memory.**
- **Unloading Whisper during synthesis.** It is about 0.15 GB and is needed for each take's word check.

**Limits:** polling cannot catch every sudden spike, so the admission check is the main protection. Readings are what macOS reports, not guarantees.
