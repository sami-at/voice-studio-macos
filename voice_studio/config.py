import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('VOICE_STUDIO_DATA', ROOT / 'local_data')).expanduser().resolve()
MODELS = ROOT / 'models'
TTS_MODEL = MODELS / 'qwen3-tts-0.6b-8bit'
CHATTERBOX_MODEL = MODELS / 'chatterbox-multilingual-v3'
STT_MODEL = MODELS / 'whisper-base'
LANGUAGES = ['English', 'French', 'Spanish', 'German', 'Italian', 'Portuguese', 'Chinese', 'Japanese', 'Korean', 'Russian']

def initialize():
    for name in ('voices', 'sessions', 'jobs', 'logs', 'cache'):
        (DATA / name).mkdir(parents=True, exist_ok=True)

def offline_environment():
    """No implicit downloads, telemetry, or global caches during normal operation."""
    return {
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
        'TOKENIZERS_PARALLELISM': 'false', 'HF_HOME': str(DATA / 'cache' / 'huggingface'),
        'XDG_CACHE_HOME': str(DATA / 'cache'), 'NUMBA_CACHE_DIR': str(DATA / 'cache' / 'numba'),
        'MPLCONFIGDIR': str(DATA / 'cache' / 'matplotlib'),
    }
