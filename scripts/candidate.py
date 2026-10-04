#!/usr/bin/env python3
"""Manage only the isolated native candidate on 127.0.0.1:18443."""
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT.parent / "reports"
PID = REPORTS / "candidate.pid"

def running():
    if not PID.exists():
        return None
    try:
        pid = int(PID.read_text())
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        cwd = (Path("/proc") / str(pid) / "cwd").resolve()
        if cwd == ROOT and b"uvicorn" in cmdline and b"openbachelors.app:app" in cmdline:
            os.kill(pid, 0)
            return pid
    except (OSError, ValueError):
        pass
    return None

def stop():
    pid = running()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            if running() is None:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Candidate did not stop; inspect its log")
    PID.unlink(missing_ok=True)

def start():
    if running():
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    with (REPORTS / "candidate-server.log").open("ab") as log:
        proc = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "uvicorn",
                "openbachelors.app:app", "--host", "127.0.0.1", "--port", "18443", "--workers", "1"],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True)
    PID.write_text(str(proc.pid))
    for _ in range(100):
        if proc.poll() is not None:
            PID.unlink(missing_ok=True)
            raise RuntimeError("Candidate failed to start; inspect reports/candidate-server.log")
        try:
            with urllib.request.urlopen("http://127.0.0.1:18443/config/prod/official/Android/version", timeout=1) as r:
                version = json.load(r)
            print(json.dumps({"pid": proc.pid, "version": version, "listen": "127.0.0.1:18443"}))
            return
        except (OSError, ValueError):
            time.sleep(0.2)
    stop()
    raise RuntimeError("Candidate startup timed out")

def main():
    REPORTS.mkdir(exist_ok=True)
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action not in {"start", "stop", "restart", "status"}:
        raise SystemExit("usage: candidate.py [start|stop|restart|status]")
    with (REPORTS / "candidate-control.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action in {"stop", "restart"}:
            stop()
        if action in {"start", "restart"}:
            start()
        if action == "status":
            print(json.dumps({"pid": running(), "listen": "127.0.0.1:18443"}))

if __name__ == "__main__":
    main()
