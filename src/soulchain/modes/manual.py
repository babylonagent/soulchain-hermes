"""
SoulChain manual mode — one-shot anchor on demand.

No daemon. Anchors changed files immediately, then exits.
Used for: ad-hoc anchoring, pre-commit hooks, cron-triggered batch sync.

    python -m soulchain.modes.manual           # anchor changed files
    python -m soulchain.modes.manual --force   # re-anchor everything
    python -m soulchain.modes.manual --status  # show on-chain status
    python -m soulchain.modes.manual --verify  # verify local vs on-chain
"""
import argparse
import json
import logging
import sys
import time

from ..core import SoulChainEngine, load_config, load_private_key

logger = logging.getLogger("soulchain.manual")


def format_hash(h: str) -> str:
    """Shorten hash for display."""
    if not h:
        return "none"
    return f"{h[:18]}...{h[-8:]}"


def run():
    parser = argparse.ArgumentParser(
        description="SoulChain — Anchor Hermes identity on-chain"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Show on-chain status")
    group.add_argument("--verify", action="store_true", help="Verify local vs on-chain")
    group.add_argument("--register", action="store_true", help="Register soul")
    group.add_argument("--file", type=str, help="Anchor specific file")
    parser.add_argument("--force", action="store_true", help="Re-anchor even if unchanged")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.json else logging.INFO,
        format="%(asctime)s [soulchain] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    private_key = load_private_key()

    # Load crypto provider if keystore exists (enables encryption + restore)
    import os as _os
    crypto = None
    keystore_path = _os.environ.get("SOULCHAIN_KEYSTORE", _os.path.expanduser("~/.soulchain/keystore.json"))
    if _os.path.exists(keystore_path):
        passphrase = _os.environ.get("SOULCHAIN_KEYSTORE_PASSWORD")
        if passphrase:
            from ..crypto import SoulCryptoProvider
            crypto = SoulCryptoProvider.from_keystore(keystore_path, passphrase)

    engine = SoulChainEngine(private_key, config=config, crypto=crypto)

    # ─── Status ───
    if args.status:
        statuses = engine.get_status()
        if args.json:
            print(json.dumps(statuses, indent=2))
        else:
            print(f"Soul: {'registered' if engine.is_registered() else 'NOT registered'}")
            print(f"Agent: {engine.address}")
            print(f"Balance: {engine.balance:.8f} ETH")
            print(f"Contract: {config['chain']['contractAddress']}")
            print()
            for s in statuses:
                vc = s.get("versionCount", 0)
                if vc > 0:
                    match = "✅" if s.get("verified") else "❌"
                    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(s["timestamp"]))
                    print(f"  {s['name']} (type {s['docType']}): v{s['version']}, {vc} version(s)")
                    print(f"    {match} hash: {format_hash(s.get('onChainHash'))}")
                    print(f"    anchored: {ts}")
                else:
                    print(f"  {s['name']} (type {s['docType']}): 0 versions")
            print()
        return

    # ─── Verify ───
    if args.verify:
        results = engine.verify_all()
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            all_ok = True
            for r in results:
                if r["verified"]:
                    print(f"  ✅ {r['name']}: MATCH (v{r.get('version', '?')})")
                else:
                    all_ok = False
                    reason = r.get("reason", "hash_mismatch")
                    print(f"  ❌ {r['name']}: {reason}")
                    if "local" in r:
                        print(f"     local:   {format_hash(r['local'])}")
                        print(f"     onChain: {format_hash(r['onChain'])}")
            print(f"\nAll verified: {'✅ YES' if all_ok else '❌ NO'}")
        sys.exit(0 if all(r["verified"] for r in results) else 1)

    # ─── Register ───
    if args.register:
        tx = engine.register_soul()
        if args.json:
            print(json.dumps({"registered": tx is not None, "tx": tx}))
        else:
            if tx:
                print(f"✅ Soul registered: {tx}")
            else:
                print("Soul already registered or registration failed")
        return

    # ─── Anchor ───
    if args.file:
        # Anchor specific file
        doc_type = 1  # Default MEMORY
        for name, info in config["trackedFiles"].items():
            if str(Path(info["path"]).expanduser().resolve()) == \
               str(Path(args.file).expanduser().resolve()):
                doc_type = info["docType"]
                break

        if args.json:
            tx = engine.anchor_file(args.file, doc_type, force=args.force)
            print(json.dumps({"file": args.file, "tx": tx}))
        else:
            print(f"Anchoring: {args.file}")
            tx = engine.anchor_file(args.file, doc_type, force=args.force)
            if tx:
                print(f"✅ Anchored: {tx}")
            else:
                print("⏭️  Skipped (unchanged or failed)")
        return

    # ─── Default: anchor all changed ───
    results = engine.anchor_all(force=args.force)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        anchored = [r for r in results if r["status"] == "anchored"]
        unchanged = [r for r in results if r["status"] == "unchanged"]
        failed = [r for r in results if r["status"] == "failed"]
        missing = [r for r in results if r["status"] == "missing"]

        for r in anchored:
            print(f"  ✅ {r['name']}: {r['tx'][:16]}...")
        for r in unchanged:
            print(f"  ⏭️  {r['name']}: unchanged")
        for r in failed:
            print(f"  ❌ {r['name']}: failed")
        for r in missing:
            print(f"  ⚠️  {r['name']}: file not found")

        print(f"\n{len(anchored)} anchored, {len(unchanged)} unchanged, {len(failed)} failed")
