"""robotctl: короткоживущий клиент для SSH и RaspController."""

import argparse
import asyncio
import json
import os
import uuid

from robot.remote.local_api import call


def _arguments():
    parser = argparse.ArgumentParser(prog="robotctl")
    parser.add_argument("--socket", default=os.environ.get("QR_ROBOT_SOCKET", "/run/qr-robot/control.sock"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    start = sub.add_parser("start")
    start.add_argument("--mode", choices=("qr", "manual"), required=True)
    sub.add_parser("stop")
    move = sub.add_parser("move")
    move.add_argument("--action", choices=("forward", "backward", "turn_left", "turn_right"), required=True)
    move.add_argument("--pwm", type=int, required=True)
    move.add_argument("--duration-ms", type=int, required=True)
    return parser.parse_args()


async def _run(args):
    params = {}
    if args.command == "start":
        params = {"mode": args.mode}
    elif args.command == "move":
        params = {"action": args.action, "pwm_pct": args.pwm, "duration_ms": args.duration_ms}
    data = {"api_v": 1, "request_id": uuid.uuid4().hex, "op": args.command, "params": params}
    if args.command in ("start", "move"):
        status = await call(args.socket, {"api_v": 1, "request_id": uuid.uuid4().hex,
                                          "op": "status", "params": {}})
        data["expected_revision"] = status["control_revision"]
    result = await call(args.socket, data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("accepted") else 1


def main():
    try:
        return asyncio.run(_run(_arguments()))
    except (OSError, asyncio.TimeoutError, ValueError) as exc:
        print(f"robotctl: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
