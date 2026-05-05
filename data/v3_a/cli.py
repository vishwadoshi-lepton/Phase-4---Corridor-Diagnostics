"""Command-line interface — ``python -m data.v3_a.cli``. Spec §12."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import EngineConfig
from .api import get_run, stream_events, submit_run, wait_for_run
from .progress import RunStatus


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser("data.v3_a.cli")
    p.add_argument("--corridor", required=True)
    p.add_argument("--anchor", required=True, help="ISO 8601 timestamp; IST assumed if no tz")
    p.add_argument("--mode", default="today_as_of_T", choices=["today_as_of_T", "retrospective"])
    p.add_argument("--out", default="-", help="output JSON path or '-' for stdout")
    p.add_argument("--progress", default="text", choices=["text", "json", "none"])
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--config-overrides", default=None, help="JSON dict merged into EngineConfig.default()")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    cfg = EngineConfig.default()
    if args.config_overrides:
        try:
            overrides = json.loads(args.config_overrides)
        except json.JSONDecodeError as e:
            print(f"--config-overrides not valid JSON: {e}", file=sys.stderr)
            return 2
        cfg = EngineConfig(**{**cfg.__dict__, **overrides})

    try:
        run_id = submit_run(args.corridor, args.anchor, mode=args.mode, config=cfg, no_cache=args.no_cache)
    except Exception as e:
        print(f"submit_run failed: {e}", file=sys.stderr)
        return 1

    if args.progress != "none":
        for ev in stream_events(run_id, timeout_sec=cfg.run_timeout_sec):
            line = (
                json.dumps(ev.to_dict())
                if args.progress == "json"
                else f"[{ev.ts}] {ev.stage} {ev.status}"
            )
            print(line, file=sys.stderr)

    rec = wait_for_run(run_id, timeout_sec=cfg.run_timeout_sec)
    if rec.status == RunStatus.FAILED:
        err = rec.error or {}
        print(f"FAILED [{err.get('code')}] {err.get('message')}", file=sys.stderr)
        if err.get("code") == "HARD_ERR_TIMEOUT":
            return 3
        return 1

    payload = json.dumps(rec.result, indent=2, default=str)
    if args.out == "-":
        print(payload)
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload)
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
