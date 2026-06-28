#!/usr/bin/env python3
"""
SoulChain for Hermes — Anchor script.

Hashes tracked Hermes files, anchors their integrity on-chain via SoulRegistry.

Usage:
    python anchor.py                    # anchor all tracked files (diff from chain)
    python anchor.py --file ~/.hermes/memories/memory.md
    python anchor.py --status           # show on-chain status
    python anchor.py --verify           # verify local files match on-chain hashes
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from web3 import Web3
from eth_account import Account

# ─── Config ───────────────────────────────────────────────────────────────────

CONTRACT_ADDRESS = "0x2AE3F15CAD486226Af839ae8FB4BbA08428283A2"
CHAIN_RPC = "https://mainnet.base.org"
CHAIN_ID = 8453
EXPLORER = "https://basescan.org"

# Hermes file paths → SoulRegistry docType mapping
# Doc types from SoulRegistry.sol: SOUL=0, MEMORY=1, AGENTS=2, USER=3, DAILY=4,
# CHAT=5, LOVE_MAP=6, MUSING=7, COACHING=8, TOOLS=9, IDENTITY=10
TRACKED_FILES = {
    "SOUL": {
        "docType": 0,
        "paths": ["~/.hermes/SOUL.md"],
    },
    "MEMORY": {
        "docType": 1,
        "paths": ["~/.hermes/memories/MEMORY.md"],
    },
    "USER": {
        "docType": 3,
        "paths": ["~/.hermes/memories/USER.md"],
    },
    "IDENTITY": {
        "docType": 10,
        "paths": ["~/.hermes/config.yaml"],
    },
}

# ─── ABI (minimal) ───────────────────────────────────────────────────────────

SOUL_REGISTRY_ABI = [
    {
        "inputs": [],
        "name": "registerSoul",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "docType", "type": "uint8"},
            {"name": "contentHash", "type": "bytes32"},
            {"name": "encryptedHash", "type": "bytes32"},
            {"name": "storageCid", "type": "string"},
            {"name": "signature", "type": "bytes"},
        ],
        "name": "writeDocument",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agent", "type": "address"},
            {"name": "docType", "type": "uint8"},
        ],
        "name": "latestDocument",
        "outputs": [
            {
                "components": [
                    {"name": "contentHash", "type": "bytes32"},
                    {"name": "encryptedHash", "type": "bytes32"},
                    {"name": "storageCid", "type": "string"},
                    {"name": "docType", "type": "uint8"},
                    {"name": "timestamp", "type": "uint64"},
                    {"name": "version", "type": "uint32"},
                    {"name": "prevHash", "type": "bytes32"},
                    {"name": "signature", "type": "bytes"},
                ],
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agent", "type": "address"},
            {"name": "docType", "type": "uint8"},
        ],
        "name": "documentCount",
        "outputs": [{"name": "", "type": "uint32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "agent", "type": "address"},
            {"name": "docType", "type": "uint8"},
            {"name": "version", "type": "uint32"},
            {"name": "expectedHash", "type": "bytes32"},
        ],
        "name": "verifyDocument",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "", "type": "address"}],
        "name": "registered",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# ─── Core functions ───────────────────────────────────────────────────────────

def get_w3_and_contract(private_key: str):
    """Initialize web3 connection and contract instance."""
    w3 = Web3(Web3.HTTPProvider(CHAIN_RPC))
    if not w3.is_connected():
        raise RuntimeError(f"Cannot connect to {CHAIN_RPC}")
    account = Account.from_key(private_key)
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=SOUL_REGISTRY_ABI)
    return w3, account, contract


def hash_file(filepath: str):
    """SHA-256 hash a file. Returns (content_hash_hex, file_content_bytes) or (None, None)."""
    path = Path(filepath).expanduser()
    if not path.exists():
        return None, None
    content = path.read_bytes()
    h = hashlib.sha256(content).digest()
    return "0x" + h.hex(), content


def register_soul(w3, account, contract):
    """One-time soul registration."""
    is_registered = contract.functions.registered(account.address).call()
    if is_registered:
        print("✅ Soul already registered")
        return True

    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.registerSoul().build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gas": 100000,
        "gasPrice": w3.eth.gas_price,
        "chainId": CHAIN_ID,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    if receipt["status"] == 1:
        print(f"✅ Soul registered: {EXPLORER}/tx/{tx_hash.hex()}")
        return True
    else:
        print(f"❌ Registration failed")
        return False


def anchor_file(w3, account, contract, doc_type: int, filepath: str, private_key: str):
    """Hash, sign, and anchor a file on-chain."""
    content_hash, content = hash_file(filepath)
    if content_hash is None:
        print(f"  ⚠️  File not found: {filepath}")
        return None

    # Check if this version already matches on-chain
    try:
        latest = contract.functions.latestDocument(account.address, doc_type).call()
        onchain_hash = "0x" + latest[0].hex()
        if "0x" + onchain_hash == content_hash:
            print(f"  ⏭️  Already anchored (v{latest[5]}, no changes)")
            return None
    except Exception:
        pass  # No previous version

    # Sign the hash (EIP-191 personal_sign)
    from eth_account.messages import encode_defunct
    msg = encode_defunct(hexstr=content_hash)
    signed_msg = Account.from_key(private_key).sign_message(msg)
    signature = signed_msg.signature

    # For Phase 1 POC: encryptedHash = contentHash (no encryption yet)
    encrypted_hash = content_hash  # Phase 1: same as content hash
    storage_cid = f"local:{filepath}"

    # Build tx data
    call_data = contract.functions.writeDocument(
        doc_type,
        bytes.fromhex(content_hash[2:]),  # bytes32
        bytes.fromhex(encrypted_hash[2:]),  # bytes32
        storage_cid,
        signature,
    )

    # Estimate gas properly
    try:
        gas_estimate = w3.eth.estimate_gas({
            "from": account.address,
            "to": Web3.to_checksum_address(CONTRACT_ADDRESS),
            "data": call_data.build_transaction({"from": account.address, "gas": 0, "gasPrice": 0, "chainId": CHAIN_ID, "nonce": 0})["data"],
        })
        gas_limit = int(gas_estimate * 1.3)
    except Exception:
        gas_limit = 250000

    nonce = w3.eth.get_transaction_count(account.address, "pending")

    # Use EIP-1559 for Base
    base_fee = w3.eth.get_block("latest")["baseFeePerGas"]
    priority_fee = max(1000, w3.eth.max_priority_fee)  # at least 0.001 gwei
    max_fee = int(base_fee * 2) + priority_fee

    tx = call_data.build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gas": gas_limit,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee,
        "chainId": CHAIN_ID,
        "type": 2,
    })

    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

    if receipt["status"] == 1:
        print(f"  ✅ Anchored: {EXPLORER}/tx/{tx_hash.hex()}")
        print(f"     Hash: {content_hash[:20]}...{content_hash[-8:]}")
        return tx_hash.hex()
    else:
        print(f"  ❌ Anchor failed for {filepath} (tx reverted)")
        print(f"     Tx: {EXPLORER}/tx/{tx_hash.hex()}")
        return None


def show_status(w3, account, contract):
    """Show on-chain status of all tracked documents."""
    is_registered = contract.functions.registered(account.address).call()
    print(f"Soul: {'registered' if is_registered else 'NOT registered'}")
    print(f"Agent address: {account.address}")
    print(f"Contract: {CONTRACT_ADDRESS}")
    print(f"Chain: Base (8453)")
    print()

    for name, info in TRACKED_FILES.items():
        doc_type = info["docType"]
        count = contract.functions.documentCount(account.address, doc_type).call()
        print(f"  {name} (type {doc_type}): {count} version(s)")
        if count > 0:
            latest = contract.functions.latestDocument(account.address, doc_type).call()
            content_hash = "0x" + latest[0].hex()
            timestamp = latest[4]
            version = latest[5]
            print(f"    Latest: v{version}, hash={content_hash[:20]}...{content_hash[-8:]}")
            print(f"    Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(timestamp))}")


def verify_local(w3, account, contract):
    """Verify local files match their on-chain hashes."""
    all_match = True
    for name, info in TRACKED_FILES.items():
        doc_type = info["docType"]
        for filepath in info["paths"]:
            expanded = os.path.expanduser(filepath)
            local_hash, _ = hash_file(expanded)
            if local_hash is None:
                continue
            try:
                latest = contract.functions.latestDocument(account.address, doc_type).call()
                onchain_hash = "0x" + latest[0].hex()
                match = local_hash == onchain_hash
                status = "✅ MATCH" if match else "❌ MISMATCH"
                print(f"  {name} ({filepath}):")
                print(f"    Local:   {local_hash[:20]}...{local_hash[-8:]}")
                print(f"    On-chain: {onchain_hash[:20]}...{onchain_hash[-8:]}")
                print(f"    {status}")
                if not match:
                    all_match = False
            except Exception as e:
                print(f"  {name}: no on-chain version yet")

    return all_match


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SoulChain — Anchor Hermes identity on-chain")
    parser.add_argument("--file", help="Anchor specific file")
    parser.add_argument("--status", action="store_true", help="Show on-chain status")
    parser.add_argument("--verify", action="store_true", help="Verify local vs on-chain")
    parser.add_argument("--register", action="store_true", help="Register soul (one-time)")
    parser.add_argument("--private-key", default=None)
    args = parser.parse_args()

    private_key = args.private_key or os.environ.get("SOULCHAIN_PRIVATE_KEY")
    if not private_key:
        # Try loading from sandbox wallet
        wallet_env = Path("/root/.chancy/secrets/sandbox-wallet.env")
        if wallet_env.exists():
            for line in wallet_env.read_text().splitlines():
                if "PRIVATE_KEY" in line and "=" in line and not line.startswith("#"):
                    private_key = line.split("=", 1)[1].strip()
                    break
    if not private_key:
        print("ERROR: No private key. Set SOULCHAIN_PRIVATE_KEY or use --private-key")
        sys.exit(1)

    w3, account, contract = get_w3_and_contract(private_key)

    if args.status:
        show_status(w3, account, contract)
        return

    if args.verify:
        ok = verify_local(w3, account, contract)
        sys.exit(0 if ok else 1)

    # Default: register + anchor
    if not register_soul(w3, account, contract):
        print("Cannot proceed without soul registration")
        sys.exit(1)

    if args.file:
        # Anchor specific file (auto-detect doc type)
        doc_type = 1  # Default to MEMORY
        for name, info in TRACKED_FILES.items():
            if any(os.path.expanduser(p) == os.path.expanduser(args.file) for p in info["paths"]):
                doc_type = info["docType"]
                break
        print(f"Anchoring: {args.file}")
        anchor_file(w3, account, contract, doc_type, args.file, private_key)
    else:
        # Anchor all tracked files
        for name, info in TRACKED_FILES.items():
            print(f"\n{name}:")
            for filepath in info["paths"]:
                print(f"  → {filepath}")
                anchor_file(w3, account, contract, info["docType"], filepath, private_key)

    print("\nDone. View on basescan: " + EXPLORER + "/address/" + CONTRACT_ADDRESS)


if __name__ == "__main__":
    main()
