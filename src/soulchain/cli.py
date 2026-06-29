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
import os
import sys
from pathlib import Path

from .core import load_config, load_private_key, DEFAULT_CONFIG, EXPLORER


def _load_engine():
    """Create a SoulChainEngine with crypto provider if keystore is available."""
    from .core import SoulChainEngine
    config = load_config()
    private_key = load_private_key()

    crypto = None
    keystore_path = os.environ.get("SOULCHAIN_KEYSTORE", os.path.expanduser("~/.soulchain/keystore.json"))
    if os.path.exists(keystore_path):
        passphrase = os.environ.get("SOULCHAIN_KEYSTORE_PASSWORD")
        if passphrase:
            from .crypto import SoulCryptoProvider
            crypto = SoulCryptoProvider.from_keystore(keystore_path, passphrase)

    return SoulChainEngine(private_key, config=config, crypto=crypto)


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

    # grant — grant access to another address
    grant_parser = subparsers.add_parser("grant", help="Grant read access to another address")
    grant_parser.add_argument("reader", type=str, help="Address to grant access to")
    grant_parser.add_argument("--doc-type", type=int, required=True, help="Doc type (0=SOUL, 1=MEMORY, 3=USER, 10=IDENTITY)")

    # revoke — revoke access
    revoke_parser = subparsers.add_parser("revoke", help="Revoke read access from an address")
    revoke_parser.add_argument("reader", type=str, help="Address to revoke access from")
    revoke_parser.add_argument("--doc-type", type=int, required=True, help="Doc type to revoke")

    # restore — restore a file from on-chain
    restore_parser = subparsers.add_parser("restore", help="Restore a file from on-chain storage")
    restore_parser.add_argument("--doc-type", type=int, required=True, help="Doc type to restore")
    restore_parser.add_argument("--version", type=int, default=None, help="Specific version (default: latest)")
    restore_parser.add_argument("--output", type=str, default=None, help="Output file path (default: stdout)")

    # hierarchy — show agent hierarchy
    hier_parser = subparsers.add_parser("hierarchy", help="Show multi-agent hierarchy")
    hier_parser.add_argument("--register-child", type=str, default=None, help="Register a child agent address")

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
        logging.basicConfig(level=logging.INFO)
        engine = _load_engine()
        if engine.is_registered():
            print("Soul already registered")
        else:
            tx = engine.register_soul()
            if tx:
                print(f"✅ Soul registered: {tx}")
            else:
                print("❌ Registration failed")
                sys.exit(1)

    elif args.command == "grant":
        logging.basicConfig(level=logging.INFO)
        engine = _load_engine()
        print(f"Granting access to {args.reader} for doc type {args.doc_type}...")
        tx = engine.grant_access(args.reader, args.doc_type)
        if tx:
            print(f"✅ Access granted: {EXPLORER}/tx/{tx}")
        else:
            print("❌ Grant failed")
            sys.exit(1)

    elif args.command == "revoke":
        logging.basicConfig(level=logging.INFO)
        engine = _load_engine()
        print(f"Revoking access from {args.reader} for doc type {args.doc_type}...")
        tx = engine.revoke_access(args.reader, args.doc_type)
        if tx:
            print(f"✅ Access revoked: {EXPLORER}/tx/{tx}")
        else:
            print("❌ Revoke failed")
            sys.exit(1)

    elif args.command == "restore":
        logging.basicConfig(level=logging.INFO)
        engine = _load_engine()
        print(f"Restoring doc type {args.doc_type} (version: {args.version or 'latest'})...")
        content = engine.restore_file(args.doc_type, args.version)
        if content is None:
            print("❌ Restore failed")
            sys.exit(1)
        if args.output:
            Path(args.output).expanduser().write_bytes(content)
            print(f"✅ Restored {len(content)}B → {args.output}")
        else:
            print(f"✅ Restored {len(content)}B:")
            sys.stdout.buffer.write(content)
            sys.stdout.buffer.write(b"\n")

    elif args.command == "hierarchy":
        logging.basicConfig(level=logging.WARNING)
        engine = _load_engine()

        if args.register_child:
            print(f"Registering child: {args.register_child}...")
            tx = engine.register_child(args.register_child)
            if tx:
                print(f"✅ Child registered: {EXPLORER}/tx/{tx}")
            else:
                print("❌ Child registration failed")
                sys.exit(1)

        h = engine.get_hierarchy()
        print(f"Agent:    {h['agent']}")
        print(f"Parent:   {h['parent'] or '(none)'}")
        if h["children"]:
            print(f"Children ({h['childCount']}):")
            for c in h["children"]:
                print(f"  - {c}")
        else:
            print("Children: (none)")


if __name__ == "__main__":
    main()
