"""Retain verified wheel downloads so interrupted installation is recoverable."""
import concurrent.futures
import json
from pathlib import Path
from urllib.parse import urlparse, unquote
from download_models import download

ROOT = Path(__file__).resolve().parent.parent

def main():
    report = json.loads((ROOT / 'docs' / 'dependency-resolution.json').read_text())
    tasks = []
    for entry in report['install']:
        info = entry['download_info']
        name = unquote(Path(urlparse(info['url']).path).name)
        if not name.endswith('.whl'):
            raise RuntimeError('Expected a binary wheel, got ' + name)
        digest = info['archive_info']['hashes']['sha256']
        tasks.append((info['url'], ROOT / '.setup-wheels' / name, digest))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(lambda args: download(*args), tasks))
    (ROOT / '.setup-wheels' / '.complete').write_text('All SHA-256 checks passed.\n')
    print('All dependency wheels are verified and retained locally.', flush=True)

if __name__ == '__main__':
    main()
