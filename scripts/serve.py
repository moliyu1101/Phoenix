"""Supervise the native API and original Phoenix/Next frontend; loopback by default."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def frontend_command(root: Path, dev: bool, host: str, port: int) -> list[str]:
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js 20+ is required. Backend-only mode: --backend-only")
    ui = root / "frontend"
    if dev:
        entry = ui / "node_modules/next/dist/bin/next"
        if not entry.is_file():
            raise ValueError("Frontend dependencies are missing. Run npm ci in frontend.")
        return [node, str(entry), "dev", "-H", host, "-p", str(port)]
    entry = ui / ".next/standalone/server.js"
    if not entry.is_file():
        raise ValueError("Frontend is not built. Run bash scripts/build-ui.sh, or start with --dev.")
    return [node, str(entry)]


def stop_children(children: list[subprocess.Popen], timeout: float = 6.0):
    for child in children:
        if child.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGTERM)
                else:
                    child.terminate()
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + timeout
    for child in children:
        try:
            child.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
            except ProcessLookupError:
                pass
            child.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Phoenix API + Phoenix frontend")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dev", action="store_true")
    mode.add_argument("--backend-only", action="store_true")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--ui-host", default="127.0.0.1")
    parser.add_argument("--ui-port", type=int, default=3001)
    args = parser.parse_args()
    if not 1024 <= args.ui_port <= 65535:
        parser.error("UI port must be between 1024 and 65535")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from phoenix.config import load_settings
    settings = load_settings(args.config)
    if args.ui_port == settings.port and not args.backend_only:
        parser.error("UI and API need different ports")
    try:
        ui_command = None if args.backend_only else frontend_command(ROOT, args.dev, args.ui_host, args.ui_port)
    except ValueError as exc:
        parser.error(str(exc))
    backend_host = "127.0.0.1" if settings.host in ("0.0.0.0", "::") else settings.host
    if ":" in backend_host:
        backend_host = "[" + backend_host + "]"
    env = dict(os.environ, PHOENIX_BACKEND=f"http://{backend_host}:{settings.port}",
               HOSTNAME=args.ui_host, PORT=str(args.ui_port), NEXT_TELEMETRY_DISABLED="1")
    children: list[subprocess.Popen] = []
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    code = 0
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "phoenix", "--config", args.config, "serve"],
                                         cwd=ROOT, env=env, start_new_session=os.name == "posix"))
        if ui_command:
            children.append(subprocess.Popen(ui_command, cwd=ROOT / "frontend", env=env,
                                             start_new_session=os.name == "posix"))
            print(f"Phoenix UI: http://{args.ui_host}:{args.ui_port}", flush=True)
        print(f"Native API: {env['PHOENIX_BACKEND']}", flush=True)
        while True:
            for child in children:
                result = child.poll()
                if result is not None:
                    print(f"Service process {child.pid} exited ({result}); stopping the other service.", flush=True)
                    return result if result > 0 else 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        code = 0
    finally:
        # Restore signal handlers while shutting down so another interrupt does not leak children.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stop_children(children)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
