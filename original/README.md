# Voice Studio — macOS Apple Silicon

A starter local desktop app for generating speech using your own recorded voice and F5-TTS.

## Prerequisites
- Apple Silicon Mac (M1 or later recommended), macOS, Homebrew
- Python **3.11** (recommended for compatibility)
- Internet access for initial dependency/model downloads
- A clean voice sample (ideally 5–15 seconds) and an exact transcript of the sample

## Install

```bash
brew install python@3.11 ffmpeg
cd /path/to/voice-studio
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

If `python3.11` is installed elsewhere, replace the absolute path with the path returned by `which python3.11`.

## Use
1. Import a UTF-8 `.txt` file or paste a script.
2. Choose an MP3/WAV/M4A recording containing clear speech. For best results, trim it to a short segment with minimal background noise.
3. Enter the **exact words spoken** in that recording.
4. Click Generate Voiceover, choose MP3 or WAV, and wait.
5. Preview the saved output.

## Notes
- This starter uses the F5-TTS CLI. The first run downloads model weights. Subsequent generations can run locally if all model assets are cached.
- Long scripts can require substantial time and memory. Start with 1–2 sentences. F5-TTS handles text chunking internally, but very long inputs should be split for reliability.
- Apple Silicon MPS acceleration depends on your PyTorch installation and available operations; CPU fallback may be slower. This starter has not been tested on your specific Mac.
- The app does not upload scripts or recordings itself; third-party packages/model downloads may access the network during setup.
- Check the licensing of the specific F5-TTS model weights before commercial use. Open-source code and model weights may have different licenses.
- This is a development starter, not a signed/notarized `.app` installer.
- Clone only voices you own or have permission to use.
