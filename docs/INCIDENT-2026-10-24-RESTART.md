# Incident: unexpected restart during the CosyVoice 3 evaluation (24 October 2026)

Investigated read-only on 25 October. No model was run, no stress test performed, nothing modified or deleted.

## Conclusion

**Cause: a kernel watchdog panic triggered by memory starvation, which the CosyVoice 3 evaluation process caused.**

- **The type of failure is certain.** The panic report states it outright: a *userspace watchdog timeout*. WindowServer, the process that draws the screen, stopped responding for 137 seconds, so the kernel restarted the Mac on purpose.
- **That memory starvation caused it is strongly supported but not proven.** At the moment of the panic:
  - a CosyVoice Python process held 7.5 GB, almost the whole 8 GB machine;
  - only 14 MB of RAM was free;
  - 3.65 GB sat in the memory compressor.

  The system log from the minutes before the restart was not retained, so no single log line says "WindowServer starved because of paging". The conclusion rests on the snapshot taken at the moment of the panic.

## Evidence

**1. Panic report.** `/Library/Logs/DiagnosticReports/Retired/panic-full-2026-10-24-233813.0002.panic`

```
panic(cpu 0 caller 0xfffffe00179b14a4): userspace watchdog timeout: no successful checkins from
WindowServer (1 induced crashes) in 137 seconds
service: WindowServer (1 induced crashes) ... last successful checkin: 137 seconds ago
service: logd / opendirectoryd / configd ... last successful checkin: 0 seconds ago
```

- Panic time: **23:38:13**, 24 October.
- The Mac came back up at **23:37:46** by the boot clock; the panic file was written while it restarted.
- The reset record (`ResetCounter-2026-10-24-233903.diag`) shows `Boot faults: wdog,reset_in_1`, meaning a watchdog reset.

The other monitored system services were healthy, so the system was not frozen as a whole. The display server alone failed to respond for over two minutes.

**2. Memory at the moment of the panic** (same report, 16 KB pages):

| | |
|---|---|
| Free | **904 pages ≈ 0.01 GB** |
| Wired (cannot be paged out) | 1.88 GB |
| Active / inactive | 1.21 / 1.16 GB |
| Compressor | 3.65 GB |
| Lifetime compressions | 882 million |

The report's `memoryPressure: false` flag contradicts the free-page count. It is a single boolean and the raw page counts are the better evidence, but I cannot explain the flag.

**3. Largest processes at the panic** (resident memory):

| Process | Resident |
|---|---:|
| **Python (pid 48955)** | **7.53 GB** |
| Google Chrome and its helpers (many processes) | 0.7–1.7 GB *each* |
| VS Code plugin helper | 0.92 GB |

**4. pid 48955 was the CosyVoice evaluation.**
- Its threads were executing in `libomp.dylib`, `libc10.dylib` and `libtorch_python.dylib`. Their build UUIDs (`F53B1E01…`, `4FE43308…`, `86076B5F…`) match the PyTorch inside `models/evaluation/cosyvoice3/env` exactly.
- It ran under Homebrew Python 3.11 (`94C32A80…`).
- Voice Studio's own environment has a different PyTorch build (`libomp` `E56FEBF1…`), which rules the app out.
- All 9 threads were waiting. The process had spent only 15 s of CPU time against 811,815 page faults: it was stalled on memory, not computing.

**5. Timing.**
- The restart falls inside the CosyVoice probe that began after the `librosa` install, around 23:33–23:35. That is the tool call whose result was lost when the session ended.
- The probe whose results I reported (8.6 GB peak footprint, about 14 GB swapped out, 148 s for 5 s of audio) ran **after** the reboot, at about 23:42.

**6. Not related:**
- `Python_2026-10-24-233255_Mac-Air.diag` is a disk-writes advisory for a different Python process (8.6 GB written over 6.5 h, most likely the downloads).
- `JetsamEvent-2026-10-25-000522.ips` is a minor post-restart kill of a system daemon (`knowledgeconstructiond`) at its own limit.

## What I got wrong

1. **The safety check missed the dangerous moment.** My harness checked memory and disk only *before loading* and *between takes*. Both checks passed: 30–34 % free before load. The memory blew up *during* model loading and the first take, where nothing was watching.
2. **I ran the probe a second time after the restart.** I did not know the Mac had crashed, because the session was interrupted. That second run was just as unsafe (8.6 GB footprint, ~14 GB swapped out). It finished only because the freshly rebooted machine had less open in Chrome.
3. **The requirement was wrong from the start.** CosyVoice 3 needs about 5 GB of fp32 weights plus working memory on the CPU. On a machine that already carried about 20 GB of swap, a 93 %-full disk and a heavy Chrome session, it should not have been launched at all.

## Safe operating limits for this Mac (M1, 8 GB, swap on a nearly full disk)

1. **One model at a time, with a peak footprint of 4.5 GB or less.**
   - Qwen3-TTS (3.6–3.8 GB) fits.
   - Chatterbox (4.4 GB) is at the limit, so close Chrome first.
   - Anything whose weights alone exceed about 3 GB in fp32 on CPU (CosyVoice 3, IndexTTS-2 official, Qwen3-TTS 1.7B) is **not safe here**.
2. **Estimate before downloading:** peak ≈ weights on disk × 1.5–2 for fp32 on CPU. If that exceeds 4.5 GB, do not run it.
3. **Pre-flight before any model run:**
   - system memory free at least 40 % (`memory_pressure`);
   - swap used under about 10 GB;
   - disk free at least 25 GB (it was 14 GB; swap files live on this disk);
   - Chrome closed. Each Chrome renderer held 0.7–1.7 GB at the panic.
4. **A live watchdog, not between-step checks.** A separate monitor process should sample every 2 seconds and kill the model process immediately if any of these happens:
   - its footprint passes 5 GB;
   - system memory free falls below 10 %;
   - swap grows by more than 2 GB in a minute.

   Model loading is when memory spikes, so the monitor must be running before the model starts loading.
5. **After any unexplained crash, investigate before running again.** If a session is interrupted during a heavy run, check `/Library/Logs/DiagnosticReports` for a new panic file before retrying anything.
6. **Housekeeping (your call; nothing done):**
   - `models/evaluation/cosyvoice3/` (6.4 GB) and the older `models/evaluation/` candidates (3.9 GB) can be deleted to give the swap room.
   - The Mac has been carrying about 20 GB of swap at idle, which is mostly the browser session.
