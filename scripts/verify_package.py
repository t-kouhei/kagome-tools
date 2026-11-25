"""Release checks that require only Python's standard library."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parent.parent
manifest = json.loads((ROOT / 'source-manifest.json').read_text(encoding='utf-8'))
origin = json.loads((ROOT / 'source-origin.json').read_text(encoding='utf-8'))
assert manifest['files'] == origin['files'], 'Original application files changed; review the formula version before publishing.'
for name, digest in manifest['files'].items():
    path = ROOT / 'engine' / 'kagome_lattice' / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
    if path.suffix == '.py':
        compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
compile((ROOT / 'browser_adapter.py').read_text(encoding='utf-8'), 'browser_adapter.py', 'exec')
with zipfile.ZipFile(ROOT / 'engine.zip') as archive:
    assert set(archive.namelist()) == {'kagome_lattice/' + name for name in manifest['files']}
    assert not any(name.lower().endswith(('.pdf', '.pptx', '.mp4', '.csv')) for name in archive.namelist())


class Links(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key not in ('href', 'src') or not value or value.startswith('#'):
                continue
            parts = urlsplit(value)
            if parts.scheme or parts.netloc:
                continue
            assert not parts.path.startswith('/'), value
            path = ROOT / unquote(parts.path)
            assert path.exists(), value


for name in ('index.html', 'app.html', 'usage.html', 'principles.html', 'guide.html'):
    Links().feed((ROOT / name).read_text(encoding='utf-8'))
assert 'formula_changes' in manifest and manifest['formula_changes'] is False
print(f'PASS: {len(manifest["files"])} original application files, package contents, Python syntax, and public HTML links.')
