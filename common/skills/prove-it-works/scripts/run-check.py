#!/usr/bin/env python3
"""Run one validation command, retaining its complete combined output."""

from __future__ import annotations

import argparse
from collections import deque
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Sequence


DEFAULT_TAIL_LINES = 40
START_FAILURE_STATUS = 127


def _nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return number


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Run a command directly and retain its complete combined output."
    )


def _parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = _parser()
    parser.add_argument(
        "--tail",
        type=_nonnegative_int,
        default=DEFAULT_TAIL_LINES,
        help=f"number of output lines to print (default: {DEFAULT_TAIL_LINES})",
    )
    if "--" in argv:
        runner_argv = argv.index("--")
        command = list(argv[runner_argv + 1 :])
    else:
        runner_argv = len(argv)
        command = []
    options = parser.parse_args(list(argv[:runner_argv]))
    if "--" not in argv:
        parser.error("expected '--' before the command")
    if not command:
        parser.error("a command is required after '--'")
    return options, command


def _create_log() -> tuple[Path, Path, object]:
    log_dir = Path(tempfile.mkdtemp(prefix="run-check-"))
    os.chmod(log_dir, 0o700)
    fd, raw_log_path = tempfile.mkstemp(prefix="output-", suffix=".log", dir=log_dir)
    os.fchmod(fd, 0o600)
    return log_dir, Path(raw_log_path), os.fdopen(fd, "wb")


def _tail(path: Path, line_count: int) -> list[bytes]:
    lines: deque[bytes] = deque(maxlen=line_count)
    with path.open("rb") as stream:
        for line in stream:
            lines.append(line)
    return list(lines)


def _diagnostic(message: str) -> None:
    try:
        os.write(2, (f"run-check: {message}\n").encode("utf-8", errors="backslashreplace"))
    except Exception:
        pass


def _safe_print(value: str, *, end: str = "\n") -> bool:
    try:
        print(value, end=end)
    except Exception as error:
        _diagnostic(f"unable to write report output: {error}")
        return False
    return True


def _print_report(log_path: Path, line_count: int, status: int) -> None:
    if not _safe_print(f"Output tail (last {line_count} lines):"):
        _diagnostic(f"report log: {log_path}")
        return

    try:
        lines = _tail(log_path, line_count)
    except Exception as error:
        _diagnostic(f"unable to read output log {log_path}: {error}")
        lines = []

    for raw_line in lines:
        try:
            line = raw_line.decode("utf-8", errors="replace")
        except Exception as error:
            _diagnostic(f"unable to decode output log {log_path}: {error}")
            break
        if not _safe_print(line, end="" if line.endswith("\n") else "\n"):
            _diagnostic(f"report log: {log_path}")
            return

    if not _safe_print(f"Log: {log_path}"):
        _diagnostic(f"report log: {log_path}")
        return
    if not _safe_print(f"Status: {status}"):
        _diagnostic(f"report log: {log_path}")
        return
    _safe_print("Result: PASS" if status == 0 else "Result: FAIL")


def _finish_stdout(log_path: Path) -> None:
    try:
        sys.stdout.flush()
    except Exception as error:
        _diagnostic(f"unable to flush report output for log {log_path}: {error}")
    finally:
        # Do not let Python's interpreter shutdown flush a broken stdout and
        # replace the command's status with its own exit code.
        sys.stdout = io.StringIO()


def _status(returncode: int) -> int:
    return 128 + -returncode if returncode < 0 else returncode


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_process_group(process_group: int) -> None:
    if not _group_exists(process_group):
        return
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + 1.0
    while _group_exists(process_group) and time.monotonic() < deadline:
        time.sleep(0.02)
    if _group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 1.0
        while _group_exists(process_group) and time.monotonic() < deadline:
            time.sleep(0.02)


def _run_with_forwarding(command: Sequence[str], log_file: object) -> int:
    if os.name != "posix":
        process = subprocess.Popen(
            command,
            shell=False,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return process.wait()

    process: subprocess.Popen[object] | None = None
    pending_signals: list[int] = []
    interrupted_signal: int | None = None
    forwarded = False

    def forward(signum: int, _frame: object) -> None:
        nonlocal interrupted_signal, forwarded
        if interrupted_signal is None:
            interrupted_signal = signum
        if process is None:
            pending_signals.append(signum)
            return
        if forwarded:
            return
        forwarded = True
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    signals = (signal.SIGINT, signal.SIGTERM)
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    previous = {signum: signal.signal(signum, forward) for signum in signals}
    signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    try:
        process = subprocess.Popen(
            command,
            shell=False,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for signum in pending_signals:
            forward(signum, None)
        group_stopped = False
        while True:
            try:
                returncode = process.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if interrupted_signal is not None:
                    _stop_process_group(process.pid)
                    group_stopped = True
                    returncode = process.wait()
                    break
        if interrupted_signal is not None:
            if not group_stopped:
                _stop_process_group(process.pid)
            if returncode == 0:
                returncode = 128 + interrupted_signal
        return returncode
    finally:
        signal.pthread_sigmask(signal.SIG_BLOCK, signals)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        signal.pthread_sigmask(signal.SIG_SETMASK, blocked)


def main(argv: Sequence[str] | None = None) -> int:
    options, command = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        _log_dir, log_path, log_file = _create_log()
    except OSError as error:
        print(f"run-check: unable to create private log: {error}", file=sys.stderr)
        return START_FAILURE_STATUS

    try:
        try:
            returncode = _run_with_forwarding(command, log_file)
        except (OSError, ValueError) as error:
            message = f"unable to start command: {error}"
            try:
                log_file.write(f"run-check: {message}\n".encode("utf-8", errors="replace"))
                log_file.flush()
            except Exception as log_error:
                _diagnostic(f"unable to write start failure to log {log_path}: {log_error}")
            _diagnostic(message)
            returncode = START_FAILURE_STATUS
    finally:
        try:
            log_file.close()
        except Exception as error:
            _diagnostic(f"unable to close output log {log_path}: {error}")

    status = _status(returncode)
    try:
        _print_report(log_path, options.tail, status)
    except Exception as error:
        _diagnostic(f"unable to report output from log {log_path}: {error}")
    _finish_stdout(log_path)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
