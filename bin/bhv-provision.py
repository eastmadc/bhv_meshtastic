#!/usr/bin/env python3
"""Small, pinned-client provisioning helper used by bhv-flasher.py."""

from __future__ import annotations

import argparse
import json
import time

from meshtastic.serial_interface import SerialInterface


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--long-name", required=True)
    parser.add_argument("--short-name", required=True)
    parser.add_argument("--timeout", type=int, default=45)
    return parser


def main() -> int:
    args = create_parser().parse_args()
    interface = SerialInterface(
        devPath=args.port,
        debugOut=None,
        noNodes=True,
        timeout=args.timeout,
    )
    try:
        interface.localNode.setOwner(
            long_name=args.long_name,
            short_name=args.short_name,
        )
        time.sleep(2)
    finally:
        interface.close()

    # Reconnect so the result is a true readback rather than the local write request.
    time.sleep(1)
    interface = SerialInterface(
        devPath=args.port,
        debugOut=None,
        noNodes=True,
        timeout=args.timeout,
    )
    try:
        node = interface.getMyNodeInfo() or {}
        user = node.get("user") or {}
        metadata = interface.metadata
        result = {
            "node_id": user.get("id"),
            "long_name": interface.getLongName(),
            "short_name": interface.getShortName(),
            "hardware_model": user.get("hwModel"),
            "firmware_version_readback": getattr(metadata, "firmware_version", None),
            "channel_url": interface.localNode.getURL(includeAll=True),
        }
        print(json.dumps(result, separators=(",", ":")))
    finally:
        interface.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
