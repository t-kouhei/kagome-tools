"""ローカルの入力・解析画面。python -m kagome_lattice.gui --profile patent"""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import uuid
import webbrowser
import zipfile
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .io import EDGE_COLS, BRANCH_COLS, ENTRANCE_COLS
from .model import KagomeModel
from .profiles import PROFILE_NAMES, profile_info
from .semantics import SOURCE_SETTINGS, migrate_state_to_source, convert_state_units, flow_from_occupancy
from . import _engine as E
from .tutorial import tutorial_state
from .workspace_history import WorkspaceHistory, atomic_json, read_json
from .examples import CATALOG, example_state
from .effects import CATALOG as EFFECT_CASES, comparison_case
from .sweep import SweepManager

COLUMNS = {"edges": EDGE_COLS, "branching": BRANCH_COLS, "entrances": ENTRANCE_COLS}
ROOT = Path(__file__).resolve().parent.parent


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.history = WorkspaceHistory(self)

    def directory(self, identifier):
        if str(uuid.UUID(identifier)) != identifier:
            raise ValueError("保存番号が不正です")
        return self.root / identifier

    def command(self, args):
        result = subprocess.run([sys.executable, "-m", "kagome_lattice", *map(str, args)],
                                cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"},
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
        if result.returncode:
            raise ValueError(result.stdout + result.stderr)
        return result.stdout

    def validate(self, state, allow_empty=False):
        if state["profile"] not in PROFILE_NAMES or state["mode"] not in ("propagate", "observe"):
            raise ValueError("版・入力方法が不正です")
        if type(state["n"]) is not int or not 1 <= state["n"] <= 10 or type(state["halo"]) is not bool:
            raise ValueError("格子サイズは1〜10で指定してください")
        if state["norm"] not in ("k", "m", "mvl") or state["tau"] not in ("count", "engine"):
            raise ValueError("計算設定が不正です")
        if state.get("global_rule", "none") not in ("none", "direction", "maxflow") or state.get("local_rule", "none") not in ("none", "lp"):
            raise ValueError("配分調整の設定が不正です")
        if state["mode"] == "observe" and any(state.get(k, "none") != "none" for k in ("global_rule", "local_rule")):
            raise ValueError("配分調整は入口の流入量から計算する場合に使用してください")
        for table, columns in COLUMNS.items():
            if len(state["tables"][table]) > 10000:
                raise ValueError("入力行が多すぎます")
            for row in state["tables"][table]:
                if set(row) != set(columns):
                    raise ValueError(f"{table}の列が入力形式と一致しません")
        model = KagomeModel(state["n"], halo=state["halo"])
        expected = {"edges": model.edges, "entrances": model.entrances,
                    "branching": [(*node, r) for node in model.nodes
                                  for r in E.CONNECTED_ROADS[node[0]]]}
        for table, keys in expected.items():
            if allow_empty and not state["tables"][table]:
                continue  # 新規生成時の空状態
            columns = COLUMNS[table][:4]
            actual = [(r[columns[0]], *[int(r[k]) for k in columns[1:]]) for r in state["tables"][table]]
            if len(actual) != len(keys) or set(actual) != set(keys):
                raise ValueError(f"{table}の場所に欠落・重複・格子との不一致があります")

    def save(self, state):
        self.validate(state)
        identifier = str(uuid.uuid4())
        directory = self.directory(identifier)
        directory.mkdir()
        atomic_json(directory / "state.json", state)
        self.history.metadata(identifier, state)
        return identifier

    def load(self, identifier):
        return read_json(self.directory(identifier) / "state.json")

    def write_input(self, directory, state):
        directory.mkdir(parents=True)
        for table, columns in COLUMNS.items():
            with (directory / (table + ".csv")).open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(state["tables"][table])
        metadata = {k: state[k] for k in ("n", "halo", "profile")}
        metadata["calculation"] = {k: state[k] for k in ("norm", "tau")}
        (directory / "lattice.json").write_text(json.dumps(metadata), encoding="utf-8")

    def initialize(self, data):
        state = {"n": data["n"], "halo": data["halo"], "profile": data["profile"],
                 "mode": "propagate", **SOURCE_SETTINGS, "theta": 0.5,
                 "name": "新しい解析", "tables": {k: [] for k in COLUMNS}}
        self.validate(state, allow_empty=True)
        identifier = str(uuid.uuid4())
        directory = self.directory(identifier)
        args = ["example", state["n"], directory / "input", "--profile", state["profile"]]
        if state["halo"]:
            args.append("--halo")
        self.command(args)
        for table in COLUMNS:
            with (directory / "input" / (table + ".csv")).open(encoding="utf-8-sig") as f:
                state["tables"][table] = list(csv.DictReader(f))
        (directory / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.history.metadata(identifier, state, kind='sample')
        return state

    def run(self, state, baseline=None):
        identifier = self.save(state)
        directory = self.directory(identifier)
        self.write_input(directory / "input", state)
        args = ["analyze", state["n"], directory / "input", directory / "result"]
        if baseline:
            before = self.load(baseline)
            for key in ("n", "halo", "profile", "mode", "norm", "tau", "theta"):
                if before[key] != state[key]:
                    raise ValueError("変更前と格子・版・計算設定をそろえてください")
            self.write_input(directory / "base", before)
            args = ["scenario", state["n"], directory / "base", directory / "input", directory / "result"]
        args += ["--profile", state["profile"], "--norm", state["norm"], "--tau", state["tau"],
                 "--theta", state["theta"]]
        if state["halo"]:
            args.append("--halo")
        if state["mode"] == "propagate":
            args.append("--entrances")
            args += ["--global", state.get("global_rule", "none"), "--local", state.get("local_rule", "none")]
            if baseline:
                args += ['--base-global', before.get('global_rule', 'none'), '--base-local', before.get('local_rule', 'none')]
        log = self.command(args)
        target = "result/scenario/viewer.html" if baseline else "result/viewer.html"
        if not (directory / target).exists():
            raise ValueError("結果画面を生成できませんでした。" + log)
        with zipfile.ZipFile(directory / "analysis.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.name != "analysis.zip":
                    archive.write(path, path.relative_to(directory))
        report_path = directory / target.replace("viewer.html", "report.json")
        local = json.loads(report_path.read_text(encoding="utf-8")).get("operations", {}).get("local", {})
        self.history.metadata(identifier, state, kind='analysis', has_result=True)
        return {"id": identifier, "url": f"/files/{identifier}/{target}",
                "archive_url": f"/files/{identifier}/analysis.zip", "log": log,
                "adjustment_resolved": local.get("resolved"), "adjustment_reason": local.get("stop_reason")}


def serve(profile=None, port=0, root=None, open_browser=True):
    workspace = Workspace(root or ROOT / "gui-work")
    sweeps = SweepManager(workspace)
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value, status=200, content_type="application/json; charset=utf-8"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                return self.reply({"error": "接続先が不正です"}, 403)
            if urlsplit(self.path).path == "/":
                page = (Path(__file__).parent / "editor.html").read_text(encoding="utf-8")
                page = page.replace("__TOKEN__", token).replace("__PROFILE__", profile or 'auto')
                return self.reply(page.encode(), content_type="text/html; charset=utf-8")
            if self.path in ("/guide.html", "/principles.html", "/usage.html", "/demonstration.html"):
                return self.reply((Path(__file__).parent / self.path[1:]).read_bytes(), content_type="text/html; charset=utf-8")
            if self.path in ("/assets/editor.css", "/assets/editor.js"):
                name = self.path.rsplit("/", 1)[1]
                mime = "text/css" if name.endswith(".css") else "text/javascript"
                return self.reply((Path(__file__).parent / name).read_bytes(), content_type=mime + "; charset=utf-8")
            if self.path.startswith("/files/"):
                try:
                    identifier, relative = self.path[len("/files/"):].split("/", 1)
                    directory = workspace.directory(identifier)
                    path = (directory / relative).resolve()
                    path.relative_to(directory)
                    if path.suffix not in (".html", ".csv", ".json", ".zip", ".txt"):
                        raise ValueError("ファイル形式が不正です")
                    mime = {".html": "text/html; charset=utf-8", ".zip": "application/zip"}.get(path.suffix, "text/plain; charset=utf-8")
                    return self.reply(path.read_bytes(), content_type=mime)
                except (ValueError, OSError):
                    pass
            self.reply({"error": "見つかりません"}, 404)

        def do_POST(self):
            if self.headers.get("X-Kagome-Token") != token:
                return self.reply({"error": "操作画面を開き直してください"}, 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8_000_000:
                    raise ValueError("入力サイズが不正です")
                data = json.loads(self.rfile.read(length))
                if self.path == "/api/init":
                    result = workspace.initialize(data)
                elif self.path == '/api/examples':
                    result = CATALOG
                elif self.path == '/api/effects':
                    result = EFFECT_CASES
                elif self.path == '/api/effect-case':
                    result = comparison_case(data['id'], data['profile'])
                elif self.path == '/api/example':
                    result = example_state(data['id'], data['profile'])
                elif self.path == '/api/sweep':
                    result = sweeps.start(data['state'], data['request'])
                elif self.path == '/api/sweep-status':
                    result = sweeps.status(data['id'])
                elif self.path == '/api/sweep-cancel':
                    result = sweeps.cancel(data['id'])
                elif self.path == '/api/startup':
                    result = workspace.history.startup(data.get('profile', 'auto'), data.get('session_id'))
                elif self.path == '/api/draft':
                    result = workspace.history.store_draft(data)
                elif self.path == '/api/duplicate':
                    result = workspace.history.duplicate(data['id'], data.get('name'))
                elif self.path == '/api/result':
                    result = workspace.history.result(data['id'])
                    if result and 'state' in data:
                        before = workspace.load(data['id'])
                        current = dict(data['state'])
                        for item in (before, current):
                            item.setdefault('global_rule', 'none')
                            item.setdefault('local_rule', 'none')
                        if before != current:
                            result = None
                elif self.path == "/api/tutorial":
                    result = tutorial_state(data["profile"])
                elif self.path == "/api/info":
                    model = KagomeModel(data["n"], halo=data["halo"])
                    result = {"profile": profile_info(data["profile"], data["norm"]),
                              "edges": [{"key": list(e), "a": model.position(e[:3]),
                                         "b": model.position(model.target(e)), "inner": model.is_inner(e)}
                                        for e in model.edges]}
                elif self.path == "/api/save":
                    result = {"id": workspace.save(data)}
                elif self.path == "/api/source-settings":
                    workspace.validate(data)
                    result = migrate_state_to_source(data)
                elif self.path == "/api/from-occupancy":
                    result = {"V": flow_from_occupancy(float(data["n"]), float(data["L"]), float(data["v"]))}
                elif self.path == "/api/normalization":
                    workspace.validate(data["state"])
                    result = convert_state_units(data["state"], data["norm"])
                elif self.path == "/api/list":
                    result = workspace.history.cases(data)
                elif self.path == "/api/load":
                    result = workspace.load(data["id"])
                elif self.path == "/api/run":
                    result = workspace.run(data["state"], data.get("baseline"))
                elif self.path == "/api/import":
                    table = data["table"]
                    reader = csv.DictReader(io.StringIO(data["csv"].lstrip("\ufeff")))
                    if reader.fieldnames != COLUMNS[table]:
                        raise ValueError("CSVの列と順序がテンプレートと一致しません")
                    result = list(reader)
                else:
                    raise ValueError("操作が見つかりません")
                self.reply(result)
            except (ValueError, KeyError, OSError, TypeError, subprocess.TimeoutExpired) as ex:
                self.reply({"error": str(ex)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        sweeps.close()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=list(PROFILE_NAMES), default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--workspace", help="保存先フォルダ（省略時はgui-work）")
    args = parser.parse_args()
    serve(args.profile, args.port, root=args.workspace, open_browser=not args.no_browser)
