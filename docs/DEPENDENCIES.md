# Dependency and source record

- Qwen3-TTS 0.6B Base weights: Apache-2.0; https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit
- Upstream Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS
- MLX Audio: MIT; https://github.com/Blaizzy/mlx-audio
- MLX: MIT; https://github.com/ml-explore/mlx
- Whisper / MLX Whisper: MIT; https://github.com/openai/whisper and https://github.com/ml-explore/mlx-examples/tree/main/whisper
- PySide6: LGPLv3/GPLv3/commercial; https://doc.qt.io/qtforpython-6/licenses.html
- imageio-ffmpeg wrapper: BSD-2-Clause; its FFmpeg executable has separate FFmpeg notices and license configuration, inspect with `-L` and `-version`.
- SoundFile: BSD-3-Clause; bundled libsndfile: LGPL.
- NumPy/SciPy: BSD licenses.

Exact installed versions are frozen in ../requirements.lock.txt. Model revisions are frozen in ../models.lock.json. Package license metadata and bundled notices remain in .venv/lib/python3.11/site-packages. This project packages a local launcher, not a redistributed frozen Python runtime.

The original starter is preserved in ../original. No user voice file was present in that starter.
