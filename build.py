"""Package the selected application files. No reference documents or saved cases."""
from pathlib import Path
import hashlib
import json
import zipfile
from scripts.render_specification import render as render_specification

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'engine' / 'kagome_lattice'
ALLOWED = {'.py', '.html', '.css', '.js'}
ADMISSION_FILES = ('README.md', 'low.json', 'high.json', 'direction-6-off.json')


def build():
    render_specification()
    render_specification('完成確認.md', 'completion.html', '先生と行う完成確認', '2026年11月26日')
    release = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
    files = sorted(p for p in SOURCE.iterdir() if p.is_file() and p.suffix in ALLOWED)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with zipfile.ZipFile(ROOT / 'engine.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'kagome_lattice/' + path.name)
    with zipfile.ZipFile(ROOT / 'desktop-tool.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'kagome_lattice/' + path.name)
        archive.writestr('requirements.txt', 'numpy\nscipy\nmatplotlib\n')
        archive.writestr('run.bat', '@echo off\r\ncd /d "%~dp0"\r\npython -m kagome_lattice.gui\r\npause\r\n')
        archive.writestr('README.txt', 'カゴメ解析ツール v' + release['application_version'] + '\n\n最初に「仕様書.html」を開くと、目的・用語・入力・計算・結果の読み方を順に確認できます。\n\n今回動作確認したPython 3.13を推奨します。このフォルダで依存を導入します。\npython -m pip install -r requirements.txt\n\nrun.bat、または次のコマンドで起動します。\npython -m kagome_lattice.gui\n\n版の指定：--profile patent（汎用） / --profile traffic（交通）\n\nブラウザ版：https://t-kouhei.github.io/kagome-tools/\n入力JSONと結果ZIPを手元にも保存してください。\n')
        archive.write(ROOT / 'specification.html', '仕様書.html')
        archive.write(ROOT / '仕様書.md', '仕様書.md')
        archive.write(ROOT / 'completion.html', '完成確認.html')
        archive.write(ROOT / '完成確認.md', '完成確認.md')
        archive.write(ROOT / 'docs/specification/kagome-structure.svg', 'docs/specification/kagome-structure.svg')
        for name in ADMISSION_FILES:
            path = ROOT / 'examples/admission' / name
            archive.write(path, path.relative_to(ROOT))
    page = (SOURCE / 'editor.html').read_text(encoding='utf-8')
    page = page.replace('href="/assets/editor.css"', 'href="./assets/editor.css"')
    page = page.replace("const API_TOKEN='__TOKEN__',INITIAL_PROFILE='__PROFILE__';", "const API_TOKEN='',INITIAL_PROFILE=new URLSearchParams(location.search).get('profile')==='traffic'?'traffic':'patent';")
    page = page.replace('<script src="/assets/editor.js" defer></script>', '<script src="./web-bridge.js" defer></script>')
    version = release['application_version']
    page = page.replace('href="./assets/editor.css"', f'href="./assets/editor.css?v={version}"')
    page = page.replace('src="./web-bridge.js"', f'src="./web-bridge.js?v={version}"')
    page = page.replace("const API_TOKEN='',", f"globalThis.KAGOME_WEB_VERSION='{version}';const API_TOKEN='',")
    for name in ('guide.html', 'principles.html', 'usage.html', 'demonstration.html'):
        page = page.replace('href="/' + name, 'href="./' + name)
        document = (SOURCE / name).read_text(encoding='utf-8').replace('href="/"', 'href="./app.html"')
        document = document.replace('href="/?demo=flow"', 'href="./app.html?profile=patent&amp;demo=flow"')
        document = document.replace('href="/?effect=', 'href="./app.html?profile=patent&amp;effect=')
        for target in ('guide.html', 'principles.html', 'usage.html', 'demonstration.html'):
            document = document.replace('href="/' + target, 'href="./' + target)
        document = document.replace('</head>', '<link rel="icon" href="./icon.svg"></head>', 1)
        if name == 'usage.html':
            document = document.replace('<main id="main">', '<main id="main"><div style="padding:18px;background:#e7f2ef;border-radius:12px;margin-bottom:20px"><strong>ブラウザ版の使い方</strong><p>公開URLから起動できます。下記のWindows用起動操作はPython版向けです。画面の入力・解析・比較は共通です。入力と結果はこのブラウザに保存され、他の端末へは自動同期されません。大切なデータはJSON・ZIPでも保存してください。</p><a href="./">ツール一覧へ戻る</a></div>')
        (ROOT / name).write_text(document, encoding='utf-8')
    page = page.replace('ローカルワークスペース', 'ブラウザ内ワークスペース')
    page = page.replace('<div class="sidebar-bottom">', '<div class="sidebar-bottom"><a href="./specification.html" target="_blank" rel="noopener">仕様書（はじめから読む） ↗</a>', 1)
    page = page.replace('<p class="hint">配分調整は入口から計算する場合に使います。', '<p class="hint"><a href="./specification.html#admission" target="_blank" rel="noopener">標準状態を使って入口の受入量を決める：説明と入力JSON ↗</a></p><p class="hint">配分調整は入口から計算する場合に使います。', 1)
    page = page.replace('</head>', '<link rel="icon" href="./icon.svg"></head>', 1)
    page = page.replace('<body>', '<body><div id="webLoading" role="status" style="position:fixed;inset:0;z-index:9999;background:#f3f6f7;display:grid;place-items:center;padding:24px"><div style="max-width:540px"><h1 style="font-size:26px">カゴメ解析を準備しています</h1><p id="webLoadingText">初回は計算環境を読み込みます。少しお待ちください。</p><p style="font-size:14px">入力と計算結果は、このブラウザに保存します。大切な結果はZIPやJSONでも保存してください。</p><button id="webRetry" hidden onclick="location.reload()">再読み込み</button><p><a href="./">ツール一覧へ戻る</a></p></div></div>')
    (ROOT / 'app.html').write_text(page, encoding='utf-8')
    (ROOT / 'assets').mkdir(exist_ok=True)
    for name in ('editor.css', 'editor.js'):
        data = (SOURCE / name).read_bytes()
        if name == 'editor.js':
            data = data.replace(b'href="/demonstration.html"', b'href="./demonstration.html"')
        (ROOT / 'assets' / name).write_bytes(data)
    (ROOT / 'source-manifest.json').write_text(json.dumps({**release, 'files': manifest}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Packaged {len(files)} application files; no reference or saved-case directories.')


if __name__ == '__main__':
    build()
