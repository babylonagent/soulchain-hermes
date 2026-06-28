#!/usr/bin/env python3
"""
SoulChain CLI — unified entry point for all sync modes.

Usage:
    soulchain anchor                    # manual: anchor changed files
    soulchain anchor --force            # manual: re-anchor everything
    soulchain anchor --status           # show on-chain status
    soulchain anchor --verify           # verify local vs on-chain
    soulchain start --mode on-write     # start on-write daemon
    soulchain start --mode interval     # start interval daemon
    soulchain config                    # show current config
"""
import argparse
import json
import logging
import sys

from .core import load_config, load_private_key, DEFAULT_CONFIG


def main():
    parser = argparse.ArgumentParser(
        prog="soulchain",
        description="SoulChain for Hermes — Sovereign AI memory, anchored on Base",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # anchor — manual one-shot
    anchor_parser = subparsers.add_parser("anchor", aliases=["sync"], help="Anchor changed files (manual mode)")
    anchor_parser.add_argument("--status", action="store_true", help="Show on-chain status")
    anchor_parser.add_argument("--verify", action="store_true", help="Verify local vs on-chain")
    anchor_parser.add_argument("--force", action="store_true", help="Re-anchor even if unchanged")
    anchor_parser.add_argument("--file", type=str, help="Anchor specific file")
    anchor_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # start — run daemon (on-write or interval)
    start_parser = subparsers.add_parser("start", help="Start a sync daemon")
    start_parser.add_argument("--mode", choices=["on-write", "interval"], default="on-write",
                              help="Sync mode (default: on-write)")

    # config — show/edit config
    config_parser = subparsers.add_parser("config", help="Show current configuration")
    config_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # register — register soul
    reg_parser = subparsers.add_parser("register", help="Register soul (one-time)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command in ("anchor", "sync"):
        from .modes.manual import run as run_manual
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        run_manual()

    elif args.command == "start":
        if args.mode == "on-write":
            from .modes.on_write import run_daemon
            run_daemon()
        elif args.mode == "interval":
            from .modes.interval import run_daemon
            run_daemon()

    elif args.command == "config":
        config = load_config()
        if hasattr(args, "json") and args.json:
            print(json.dumps(config, indent=2))
        else:
            print(f"Sync mode: {config.get('syncMode', 'on-write')}")
            print(f"Interval:  {config.get('syncIntervalSec', 300)}s")
            print(f"Debounce:  {config.get('debounceMs', 2000)}ms")
            print(f"RPC:       {config.get('chain', {}).get('rpcUrl', 'default')}")
            print(f"Contract:  {config.get('chain', {}).get('contractAddress', 'N/A')}")
            print(f"\nTracked files:")
            for name, info in config["trackedFiles"].items():
                print(f"  {name} (type {info['docType']}): {info['path']}")

    elif args.command == "register":
        from .core import SoulChainEngine
        logging.basicConfig(level=logging.INFO)
        engine = SoulChainEngine(load_private_key(), config=load_config())
        if engine.is_registered():
            print("Soul already registered")
        else:
            tx = engine.register_soul()
            if tx:
                print(f"✅ Soul registered: {tx}")
            else:
                print("❌ Registration failed")
                sys.exit(1)


if __name__ == "__main__":
    main()
