"""Hardware/dependency report without hardware identifiers or personal files."""
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
report = {
    'macos': platform.mac_ver()[0], 'architecture': platform.machine(),
    'python': platform.python_version(), 'python_executable': sys.executable,
    'disk_free_gib': round(shutil.disk_usage(ROOT).free / 1024**3, 2),
    'packages': {},
}
for package in ['PySide6', 'mlx', 'mlx-audio', 'mlx-whisper', 'numpy', 'scipy', 'torch', 'imageio-ffmpeg']:
    try:
        report['packages'][package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        report['packages'][package] = 'missing'
try:
    import mlx.core as mx
    report['metal_available'] = mx.metal.is_available()
    report['metal_device'] = mx.metal.device_info()
    a = mx.ones((64, 64))
    b = a @ a
    mx.eval(b)
    report['metal_matrix_result'] = float(b[0, 0])
except Exception as exc:
    report['metal_error'] = str(exc)
try:
    import imageio_ffmpeg
    binary = imageio_ffmpeg.get_ffmpeg_exe()
    report['ffmpeg'] = binary
    report['ffmpeg_version'] = subprocess.check_output([binary, '-version'], text=True).splitlines()[0]
except Exception as exc:
    report['ffmpeg_error'] = str(exc)
(ROOT / 'docs' / 'environment.json').write_text(json.dumps(report, indent=2, default=str))
print(json.dumps(report, indent=2, default=str))
