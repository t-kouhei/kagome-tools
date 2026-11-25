# カゴメ解析ツール・ブラウザ版

汎用版と交通版を同じURLから利用するためのGitHub Pages配信リポジトリ。

## 機能

元のv1.0.0のPython計算コードと入力画面を使用し、PyodideのWorkerで計算する。
基本解析、変更前後の比較、条件の一括比較、CSV/JSON入出力、結果ZIP保存を提供する。
数学的定義やレビューで提案された評価式の変更は含めない。

入力・結果はブラウザのIndexedDBに保存する。別の端末には自動同期されない。
結果のURLは、そのブラウザ内の結果を開くためのもの。他人には結果ZIPを共有する。
重要な入力・結果はJSON/ZIPでも保存すること。初回起動にはネット接続が必要。

## ビルドと確認

```text
python build.py
python -m http.server 8080
```

http://localhost:8080/ から開く。ファイルを直接開く方法には対応しない。
公開時はGitHub PagesのSourceをGitHub Actionsに設定する。mainへのpushで再公開する。

`engine/kagome_lattice` は元ツールから選んだアプリファイルのみ。
`source-manifest.json` にSHA-256を記録する。
動画、先生のPDF/PowerPoint、保存ケース、個別の観測データ、レビュー資料は含めない。

ブラウザ接続部分は `browser_adapter.py` / `worker.mjs` / `web-bridge.js` / `sw.js`。
数式の計算は `engine/kagome_lattice` に一本化している。
Python版も同じアプリファイルからビルドする。

動作確認の範囲と再実行の方法は [VALIDATION.md](VALIDATION.md) を参照。

Pyodide v314.0.8と対応するNumPy/SciPyを使用。
参考: https://pyodide.org/en/stable/usage/webworker.html
