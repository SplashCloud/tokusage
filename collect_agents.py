#!/usr/bin/env python3
"""collect_agents.py — emit token usage from coding agents as JSONL (tokusage format).

Reads usage from the local data directories of three coding agents and prints
one JSON object per line to stdout:

    {"ts": "...", "model": "...", "prompt_tokens": N,
     "completion_tokens": N, "total_tokens": N, "id": "..."}

Sources (all under the user's home; missing directories are skipped silently):
  - omp         ~/.omp/agent/sessions/**/*.jsonl   (lines with type == "model_usage")
  - codex       ~/.codex/sessions/**/rollout-*.jsonl.zst / *.jsonl  (token_usage_record)
  - claude code ~/.claude/projects/**/*.jsonl      (assistant lines with usage)

Works on Windows and Linux. codex rollouts are zstd-compressed and need `pyzstd`
(pure-Python, `pip install pyzstd`) or `zstandard`; if neither is available,
codex is skipped with a warning on stderr.

Optional: --days N   only emit records no older than N days (default: no limit).
"""

import argparse
import glob
import json
import os
import sys


def warn(msg):
    print(msg, file=sys.stderr)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _emit(ts, model, prompt, completion, total, rid, cache_read=0, cache_write=0):
    print(json.dumps(
        {
            "ts": ts,
            "model": model,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "total_tokens": total,
            "id": rid,
        },
        ensure_ascii=False,
    ))


def _iter_jsonl(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _glob(base, patterns):
    out = []
    for pat in patterns:
        out.extend(glob.glob(os.path.join(base, pat), recursive=True))
    return out


def _in_window(ts, min_ts):
    """True if ts (ISO string) is >= min_ts (epoch float) or min_ts is None."""
    if min_ts is None:
        return True
    if isinstance(ts, (int, float)):
        return ts >= min_ts
    try:
        from datetime import datetime
        s = str(ts).strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp() >= min_ts
    except (ValueError, TypeError):
        return True


# --------------------------------------------------------------------------- #
# omp
# --------------------------------------------------------------------------- #

_OMP_OPERATION_TYPES = ("compaction", "branch_summary", "usage")


def read_omp(min_ts):
    base = os.path.join(os.path.expanduser("~"), ".omp", "agent", "sessions")
    count = 0
    for path in _glob(base, ["**/*.jsonl"]):
        for o in _iter_jsonl(path):
            ts = o.get("timestamp")
            if not ts or not _in_window(ts, min_ts):
                continue
            t = o.get("type")
            src = None
            if t == "message":
                # main agent turns: usage lives on the assistant message
                msg = o.get("message")
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    src = msg
            elif t in _OMP_OPERATION_TYPES:
                # standalone billed operations carry usage at the record root
                src = o
            if src is None:
                continue
            u = src.get("usage")
            model = src.get("model")
            if not isinstance(u, dict) or not model:
                continue
            provider = src.get("provider")
            if provider and "/" not in str(model):
                model = f"{provider}/{model}"
            prompt = _int(u.get("input"))
            completion = _int(u.get("output"))
            cache_read = _int(u.get("cacheRead"))
            cache_write = _int(u.get("cacheWrite"))
            total = _int(u.get("totalTokens")) or (prompt + completion + cache_read + cache_write)
            if not total:
                continue
            rid = o.get("id")
            _emit(ts, str(model), prompt, completion, total, ("omp:" + str(rid)) if rid else None,
                  cache_read, cache_write)
            count += 1
    return count


# --------------------------------------------------------------------------- #
# claude code
# --------------------------------------------------------------------------- #

def read_claude(min_ts):
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    count = 0
    for path in _glob(base, ["**/*.jsonl"]):
        for o in _iter_jsonl(path):
            u = o.get("usage")
            msg = o.get("message")
            if not isinstance(u, dict) and isinstance(msg, dict):
                u = msg.get("usage")
            if not isinstance(u, dict):
                continue
            ts = o.get("timestamp")
            if not ts or not _in_window(ts, min_ts):
                continue
            model = o.get("model") or "unknown"
            prompt = _int(u.get("input_tokens"))
            cache_read = _int(u.get("cache_read_input_tokens"))
            cache_write = _int(u.get("cache_creation_input_tokens"))
            completion = _int(u.get("output_tokens"))
            total = prompt + completion + cache_read + cache_write
            if not total:
                continue
            rid = o.get("requestId") or o.get("uuid") or o.get("id")
            _emit(ts, str(model), prompt, completion, total, ("claude:" + str(rid)) if rid else None,
                  cache_read, cache_write)
            count += 1
    return count


# --------------------------------------------------------------------------- #
# codex
# --------------------------------------------------------------------------- #

def _zstd_decompress(data):
    try:
        import pyzstd  # pure-python
        return pyzstd.decompress(data)
    except ImportError:
        pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(data)
    except ImportError:
        pass
    # last resort: system zstd/zstdcat/unzstd CLI
    import subprocess
    for prog in ("zstd", "zstdcat", "unzstd"):
        try:
            p = subprocess.run([prog, "-d", "-c", "-"], input=data, capture_output=True, timeout=60)
            if p.returncode == 0:
                return p.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    raise RuntimeError("no zstd backend (install pyzstd or zstandard, or the zstd CLI)")


def _read_codex_file(path):
    """Yield parsed JSON lines from a codex rollout file (.zst or .jsonl)."""
    if path.endswith(".zst"):
        with open(path, "rb") as fh:
            text = _zstd_decompress(fh.read()).decode("utf-8", errors="replace")
    else:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def read_codex(min_ts):
    base = os.path.join(os.path.expanduser("~"), ".codex", "sessions")
    files = sorted(_glob(base, ["**/*.jsonl.zst", "**/*.jsonl"]))
    if not files:
        return 0
    # thread_id -> current model, carried across files in chronological order
    thread_models = {}
    count = 0
    try:
        for path in files:
            for o in _read_codex_file(path):
                p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
                t = o.get("type")
                if t == "event_msg" and p.get("type") == "thread_settings_applied":
                    settings = p.get("thread_settings") or {}
                    if settings.get("model") and p.get("thread_id"):
                        thread_models[p["thread_id"]] = settings["model"]
                elif t == "token_usage_record":
                    u = p.get("usage")
                    if not isinstance(u, dict):
                        continue
                    ts = o.get("timestamp")
                    if not ts or not _in_window(ts, min_ts):
                        continue
                    model = thread_models.get(p.get("thread_id")) or "unknown"
                    inp = _int(u.get("input_tokens"))
                    cached = _int(u.get("cached_input_tokens"))
                    prompt = max(0, inp - cached)
                    cache_read = cached
                    cache_write = _int(u.get("cache_write_input_tokens"))
                    completion = _int(u.get("output_tokens"))
                    total = _int(u.get("total_tokens")) or (prompt + completion + cache_read + cache_write)
                    if not total:
                        continue
                    rid = p.get("response_id") or p.get("turn_id")
                    _emit(ts, str(model), prompt, completion, total,
                          ("codex:" + str(rid)) if rid else None, cache_read, cache_write)
                    count += 1
    except RuntimeError as e:
        warn(f"codex: skipped ({e})")
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=0,
                    help="only emit records no older than this many days (default: all)")
    args = ap.parse_args()

    min_ts = None
    if args.days and args.days > 0:
        import time
        min_ts = time.time() - args.days * 86400

    for reader in (read_omp, read_codex, read_claude):
        try:
            reader(min_ts)
        except Exception as e:  # noqa: BLE001 — one agent must not kill the rest
            warn(f"{reader.__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
