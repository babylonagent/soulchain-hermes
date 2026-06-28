#!/usr/bin/env python3
"""
SoulChain — Deploy SoulRegistry contract to Base.

Usage:
    python deploy.py --chain base
    python deploy.py --chain base-sepolia
"""
import argparse
import json
import os
import sys
from pathlib import Path

from web3 import Web3
from eth_account import Account

# Contract artifact (compiled with original upstream Hardhat)
ARTIFACT_PATH = Path(__file__).parent.parent / "contracts" / "artifacts" / "SoulRegistry.json"
SOURCE_SOL_PATH = Path(__file__).parent.parent / "contracts" / "src" / "SoulRegistry.sol"

CHAINS = {
    "base": {
        "name": "Base",
        "rpc_url": "https://mainnet.base.org",
        "chain_id": 8453,
        "explorer": "https://basescan.org",
    },
    "base-sepolia": {
        "name": "Base Sepolia",
        "rpc_url": "https://sepolia.base.org",
        "chain_id": 84532,
        "explorer": "https://sepolia.basescan.org",
    },
}


def load_artifact():
    """Load compiled contract artifact. If not present, compile from source."""
    if ARTIFACT_PATH.exists():
        with open(ARTIFACT_PATH) as f:
            return json.load(f)

    # Try the upstream artifact from clone
    upstream = Path("/tmp/soulchain-inspect/packages/contracts/artifacts/contracts/SoulRegistry.sol/SoulRegistry.json")
    if upstream.exists():
        with open(upstream) as f:
            artifact = json.load(f)
        # Save to our artifacts dir
        ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ARTIFACT_PATH, "w") as f:
            json.dump(artifact, f, indent=2)
        return artifact

    print(f"ERROR: No compiled artifact found at {ARTIFACT_PATH}")
    print("Run: cd contracts && solc --bin --abi src/SoulRegistry.sol -o artifacts/")
    sys.exit(1)


def deploy(chain_key: str, private_key: str):
    chain = CHAINS[chain_key]
    w3 = Web3(Web3.HTTPProvider(chain["rpc_url"]))

    if not w3.is_connected():
        print(f"ERROR: Cannot connect to {chain['rpc_url']}")
        sys.exit(1)

    account = Account.from_key(private_key)
    balance = w3.eth.get_balance(account.address)
    balance_eth = w3.from_wei(balance, "ether")

    print(f"Chain:        {chain['name']} (ID: {chain['chain_id']})")
    print(f"Deployer:     {account.address}")
    print(f"Balance:      {balance_eth} ETH")
    print(f"Gas price:    {w3.from_wei(w3.eth.gas_price, 'gwei')} gwei")

    artifact = load_artifact()
    bytecode = artifact["bytecode"]
    abi = artifact["abi"]

    # Deploy
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(account.address)

    tx = contract.constructor().build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gas": 600000,
        "gasPrice": w3.eth.gas_price,
        "chainId": chain["chain_id"],
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"\nTx sent:      {tx_hash.hex()}")

    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    contract_addr = receipt["contractAddress"]

    print(f"Status:       {'✅ SUCCESS' if receipt['status'] == 1 else '❌ FAILED'}")
    print(f"Block:        {receipt['blockNumber']}")
    print(f"Gas used:     {receipt['gasUsed']}")
    print(f"Gas cost:     {w3.from_wei(receipt['gasUsed'] * receipt['effectiveGasPrice'], 'ether')} ETH")
    print(f"Contract:     {contract_addr}")
    print(f"Explorer:     {chain['explorer']}/address/{contract_addr}")

    if receipt["status"] == 1:
        # Save deployment record
        deploy_record = {
            "chain": chain_key,
            "chainId": chain["chain_id"],
            "contractAddress": contract_addr,
            "deployer": account.address,
            "txHash": tx_hash.hex(),
            "blockNumber": receipt["blockNumber"],
            "gasUsed": receipt["gasUsed"],
            "deployedAt": w3.eth.get_block(receipt["blockNumber"])["timestamp"],
        }
        record_path = Path(__file__).parent.parent / "contracts" / "deployment.json"
        with open(record_path, "w") as f:
            json.dump(deploy_record, f, indent=2)
        print(f"\nSaved deployment record: {record_path}")

    return contract_addr


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy SoulRegistry to Base")
    parser.add_argument("--chain", choices=list(CHAINS.keys()), required=True)
    parser.add_argument("--private-key", default=None, help="Private key (or set SOULCHAIN_PRIVATE_KEY env)")
    args = parser.parse_args()

    private_key = args.private_key or os.environ.get("SOULCHAIN_PRIVATE_KEY")
    if not private_key:
        print("ERROR: No private key. Pass --private-key or set SOULCHAIN_PRIVATE_KEY")
        sys.exit(1)

    deploy(args.chain, private_key)
