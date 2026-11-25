# カゴメ解析ツール・ブラウザ版

汎用版と交通版を同じURLから利用するためのGitHub Pages配信リポジトリ。

## 機能

v1.0.2の共通Python計算コードと入力画面を使用し、PyodideのWorkerで計算する。
基本解析、変更前後の比較、条件の一括比較、CSV/JSON入出力、結果ZIP保存を提供する。
同じ面の標準との差と全体の標準平均との差を併記する。仮のスピン積は参考欄に置き、標準回転の絶対値平均が0なら算定保留にする。容量は正の有限値に限定する。基本の格子接続と回転式はv1.0.0から保持する。

[先生向けの5分操作例](https://t-kouhei.github.io/kagome-tools/demonstration.html)から、Vだけを1600→2400に変える実演を開始できる。

[変化が分かる5つの比較例](https://t-kouhei.github.io/kagome-tools/app.html?profile=patent&effect=bottleneck&v=1.0.2)では、流量、回転の成分、比較基準、速度、配分調整をそれぞれ固定条件付きで比較する。結果の冒頭に変更前・変更後・差を示し、同じ情報を結果HTMLとZIPに保存する。配分調整を変えた比較では変更前の設定を保持する。

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
`source-origin.json`はv1.0.0の記録、`release-source.json`は今回レビューしたv1.0.2の記録。`release.json`に定義の改訂と、基本回転式を維持したことを記録する。
動画、先生のPDF/PowerPoint、保存ケース、個別の観測データ、レビュー資料は含めない。

ブラウザ接続部分は `browser_adapter.py` / `worker.mjs` / `web-bridge.js` / `sw.js`。
数式の計算は `engine/kagome_lattice` に一本化している。
Python版も同じアプリファイルからビルドする。

動作確認の範囲と再実行の方法は [VALIDATION.md](VALIDATION.md) を参照。

Pyodide v314.0.8と対応するNumPy/SciPyを使用。
参考: https://pyodide.org/en/stable/usage/webworker.html
