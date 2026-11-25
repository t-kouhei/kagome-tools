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
approved = json.loads((ROOT / 'release-source.json').read_text(encoding='utf-8'))
assert manifest['files'] == approved['files'], 'Application files differ from the reviewed release snapshot.'
assert manifest['files']['_engine.py'] == origin['files']['_engine.py'], 'Basic lattice rotation engine changed.'
assert manifest['definition_revision'] == 'kagome-source-routing-20261125.2'
for name, digest in manifest['files'].items():
    path = ROOT / 'engine' / 'kagome_lattice' / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
    if path.suffix == '.py':
        compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
compile((ROOT / 'browser_adapter.py').read_text(encoding='utf-8'), 'browser_adapter.py', 'exec')
with zipfile.ZipFile(ROOT / 'engine.zip') as archive:
    assert set(archive.namelist()) == {'kagome_lattice/' + name for name in manifest['files']}
    assert not any(name.lower().endswith(('.pdf', '.pptx', '.mp4', '.csv')) for name in archive.namelist())
with zipfile.ZipFile(ROOT / 'desktop-tool.zip') as archive:
    assert archive.read('仕様書.md') == (ROOT / '仕様書.md').read_bytes()
    assert archive.read('仕様書.html') == (ROOT / 'specification.html').read_bytes()
    assert archive.read('完成確認.md') == (ROOT / '完成確認.md').read_bytes()
    assert archive.read('完成確認.html') == (ROOT / 'completion.html').read_bytes()


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


for name in ('index.html', 'app.html', 'usage.html', 'principles.html', 'guide.html', 'demonstration.html', 'specification.html', 'completion.html'):
    Links().feed((ROOT / name).read_text(encoding='utf-8'))
assert manifest['basic_rotation_formula_changed'] is False
print(f'PASS: {len(manifest["files"])} release files, unchanged lattice engine, package contents, Python syntax, and public HTML links.')
