"""Render the single Markdown specification as a portable Japanese HTML book."""
import base64
import json
from pathlib import Path
import re

import markdown

ROOT = Path(__file__).resolve().parent.parent


def render(source_name='仕様書.md', output_name='specification.html', title='カゴメ解析ツール 仕様書', updated='2026年11月26日'):
    source = (ROOT / source_name).read_text(encoding='utf-8')
    document = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc', 'sane_lists'],
                                 extension_configs={'toc': {'toc_depth': '2-3'}})
    body = document.convert(source)
    for path in (ROOT / 'docs/specification').glob('*.svg'):
        encoded = base64.b64encode(path.read_bytes().replace(b'\r\n', b'\n')).decode('ascii')
        body = body.replace('src="docs/specification/' + path.name + '"', 'src="data:image/svg+xml;base64,' + encoded + '"')
    body = re.sub(r'(<table>.*?</table>)', r'<div class="table-wrap">\1</div>', body, flags=re.S)
    style = '''
:root{font:16px/1.95 "Yu Gothic UI",Meiryo,sans-serif;color:#223b44;background:#f3f6f5;--line:#dbe5e0;--green:#176f65}*{box-sizing:border-box}body{margin:0}a{color:var(--green);text-underline-offset:3px}.layout{max-width:1420px;margin:auto;display:grid;grid-template-columns:260px minmax(0,960px);gap:34px;padding:32px 24px}aside{position:sticky;top:24px;align-self:start;max-height:calc(100vh - 48px);overflow:auto;font-size:12px;padding:18px 12px}.brand{font:600 11px/1.7 sans-serif;letter-spacing:.12em;color:var(--green)}summary{font-size:15px;font-weight:700;cursor:pointer}.toc ul{list-style:none;padding-left:0}.toc ul ul{padding-left:14px}.toc li{margin:7px 0;line-height:1.65}.toc a{text-decoration:none;color:#536d70}.toc a:hover{text-decoration:underline;color:var(--green)}article{min-width:0;background:#fff;padding:44px 50px;border:1px solid var(--line);border-radius:12px}h1{font-size:32px;line-height:1.5;margin:0 0 18px}h2{font-size:24px;line-height:1.6;border-top:1px solid var(--line);padding-top:27px;margin:42px 0 16px;scroll-margin-top:20px}h3{font-size:18px;margin:25px 0 10px;scroll-margin-top:20px}p{margin:14px 0}li{margin:7px 0}strong{font-weight:700;color:#154f49}img{max-width:100%;height:auto;display:block;margin:20px auto}pre{overflow:auto;background:#edf4f1;border-radius:7px;border-left:3px solid #5caa96;padding:18px;font:14px/1.8 Consolas,Meiryo,monospace}code{font-size:.9em;background:#edf4f1;border-radius:3px;padding:2px 4px}pre code{padding:0;background:none}.table-wrap{overflow:auto;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.8}td,th{border-bottom:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top;min-width:80px}th{background:#edf4f1;font-weight:600}table td:first-child{min-width:95px}.actions{display:flex;gap:13px;flex-wrap:wrap;margin:16px 0}.actions a,.actions button{font:inherit;font-size:12px;cursor:pointer;border:1px solid #c7dcd4;background:white;padding:6px 10px;border-radius:6px;text-decoration:none;color:var(--green)}.foot{margin-top:40px;padding-top:18px;border-top:1px solid var(--line);font-size:12px;color:#647977}@media(max-width:980px){.layout{display:block;padding:14px}aside{position:static;max-height:none;padding:14px 8px}article{padding:28px 22px}.toc{max-height:55vh;overflow:auto}h1{font-size:27px}h2{font-size:22px}.table-wrap{margin-left:-4px;margin-right:-4px}td,th{padding:8px;font-size:12px}}@media print{@page{size:A4;margin:17mm}body{background:white;font-size:10pt;line-height:1.75}.layout{display:block;padding:0;max-width:none}aside,.actions{display:none}article{border:0;padding:0}h1{font-size:23pt}h2{font-size:16pt;break-after:avoid}h3{break-after:avoid}pre,tr,img{break-inside:avoid}.table-wrap{overflow:visible}table{font-size:8pt}a{color:#243f44}h2{margin-top:25px;padding-top:16px}}
'''
    html = '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="カゴメ解析ツールの目的、用語、入力、計算、基準との比較を最初から説明する仕様書。"><title>カゴメ解析ツール 仕様書</title><style>' + style + '</style></head><body><div class="layout"><aside><p class="brand">KAGOME / SPECIFICATION</p><details id="contents" open><summary>仕様書の目次</summary>' + document.toc + '</details><div class="actions"><a href="./">ツール一覧</a><a href="./仕様書.md">Markdown原文</a><button onclick="window.print()">印刷・PDF保存</button></div></aside><article>' + body + '<p class="foot">対象 v1.0.2 ／ 文書更新 2026年11月25日 ／ 本文と図はこのHTML内に保存されています。</p></article></div><script>if(matchMedia("(max-width:980px)").matches)document.getElementById("contents").open=false;</script></body></html>'
    html = html.replace('href="./">ツール一覧', 'href="https://t-kouhei.github.io/kagome-tools/">ツール一覧')
    html = html.replace('<title>カゴメ解析ツール 仕様書</title>', '<title>' + title + '</title>')
    version = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))['application_version']
    html = html.replace('対象 v1.0.2', '対象 v' + version)
    html = html.replace('文書更新 2026年11月25日', '文書更新 ' + updated)
    if source_name != '仕様書.md':
        html = html.replace('仕様書の目次', '完成確認の目次').replace('KAGOME / SPECIFICATION', 'KAGOME / COMPLETION REVIEW')
        html = html.replace('href="./仕様書.md"', 'href="./' + source_name + '"')
        html = html.replace('カゴメ解析ツールの目的、用語、入力、計算、基準との比較を最初から説明する仕様書。', '先生の想定する入力・期待値・ソフト出力・保存結果を照合する完成確認用紙。')
    (ROOT / output_name).write_text(html + '\n', encoding='utf-8', newline='\n')
    print('Rendered ' + output_name + ' from one Markdown source.')


if __name__ == '__main__':
    render()
