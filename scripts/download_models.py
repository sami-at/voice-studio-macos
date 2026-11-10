"""Explicit one-time network setup. Runtime never calls this script."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent.parent

def download(url, target, expected=None, size=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    def checksum(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    if target.exists() and (size is None or target.stat().st_size == size) and (not expected or checksum(target) == expected):
        print('Already present:', target.relative_to(ROOT), flush=True)
        return
    part = target.with_suffix(target.suffix + '.part')
    if part.exists() and expected and checksum(part) == expected:
        os.replace(part, target)
        print('Recovered:', target.relative_to(ROOT), flush=True)
        return
    for attempt in range(4):
        offset = part.stat().st_size if part.exists() else 0
        if size is not None and offset == size:
            break
        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
        try:
            with urllib.request.urlopen(request, timeout=120) as source:
                mode = 'ab' if offset and source.status == 206 else 'wb'
                with part.open(mode) as out:
                    while block := source.read(1024 * 1024):
                        out.write(block)
            if size is not None and part.stat().st_size != size:
                raise OSError('Download ended early')
            break
        except (OSError, urllib.error.URLError):
            if attempt == 3:
                raise
            print('Retrying:', target.relative_to(ROOT), flush=True)
            time.sleep(2 ** attempt)
    if expected and checksum(part) != expected:
        part.unlink(missing_ok=True)
        raise RuntimeError('Checksum mismatch: ' + str(target))
    os.replace(part, target)
    print('Downloaded:', target.relative_to(ROOT), flush=True)

def main():
    lock = json.loads((ROOT / 'models.lock.json').read_text())
    tasks = []
    for model in lock.values():
        base = f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/"
        url = f"https://huggingface.co/api/models/{model['repo']}/tree/{model['revision']}?recursive=true"
        files = json.load(urllib.request.urlopen(url, timeout=60))
        for entry in files:
            name = entry['path']
            if entry['type'] != 'file' or name.startswith('.'):
                continue
            tasks.append((base + name, ROOT / 'models' / model['directory'] / name, entry.get('lfs', {}).get('oid'), entry.get('size')))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(lambda t: download(*t), tasks))
    for model in lock.values():
        (ROOT / 'models' / model['directory'] / '.complete').write_text(model['revision'] + '\n')
    download('https://keithito.com/LJ-Speech-Dataset/LJ025-0076.wav', ROOT / 'samples' / 'lj-speech-public-domain.wav')
    (ROOT / 'samples' / 'reference.txt').write_text('Many animals of even complex structure which live parasitically within others are wholly devoid of an alimentary cavity.\n')
    download('https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/LICENSE', ROOT / 'docs' / 'QWEN-LICENSE.txt')
    print('All model assets are installed.', flush=True)

if __name__ == '__main__':
    main()
