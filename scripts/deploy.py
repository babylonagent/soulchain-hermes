#!/usr/bin/env python3
"""
SoulChain — Deploy SoulRegistry contract to any EVM chain.

Usage:
    python deploy.py --chain base --private-key 0x...
    python deploy.py --chain base-sepolia --private-key 0x...
    python deploy.py --rpc-url https://my-chain.example.com --private-key 0x...
"""
import argparse
import json
import sys
from pathlib import Path

from web3 import Web3
from eth_account import Account
import solcx

CONTRACT_SOURCE = Path(__file__).parent.parent / "contracts" / "src" / "SoulRegistry.sol"

CHAINS = {
    "base": {"name": "Base", "rpc_url": "https://mainnet.base.org", "chain_id": 8453, "explorer": "https://basescan.org"},
    "base-sepolia": {"name": "Base Sepolia", "rpc_url": "https://sepolia.base.org", "chain_id": 84532, "explorer": "https://sepolia.basescan.org"},
    "arbitrum": {"name": "Arbitrum One", "rpc_url": "https://arb1.arbitrum.io/rpc", "chain_id": 42161, "explorer": "https://arbiscan.io"},
    "optimism": {"name": "Optimism", "rpc_url": "https://mainnet.optimism.io", "chain_id": 10, "explorer": "https://optimistic.etherscan.io"},
    "polygon": {"name": "Polygon", "rpc_url": "https://polygon-rpc.com", "chain_id": 137, "explorer": "https://polygonscan.com"},
    "ethereum": {"name": "Ethereum", "rpc_url": "https://eth.drpc.org", "chain_id": 1, "explorer": "https://etherscan.io"},
}


def compile_contract():
    """Compile SoulRegistry.sol and return (abi, bytecode)."""
    with open(CONTRACT_SOURCE) as f:
        source = f.read()

    solcx.install_solc("0.8.24")
    standard_input = {
        "language": "Solidity",
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
        },
        "sources": {"SoulRegistry.sol": {"content": source}},
    }
    result = solcx.compile_standard(standard_input, solc_version="0.8.24")
    contract_data = result["contracts"]["SoulRegistry.sol"]["SoulRegistry"]
    return contract_data["abi"], "0x" + contract_data["evm"]["bytecode"]["object"]


def deploy(chain_key, rpc_url, chain_id, explorer, private_key):
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to {rpc_url}")
        sys.exit(1)

    account = Account.from_key(private_key)
    balance = w3.eth.get_balance(account.address)

    print(f"Chain:      {chain_key} (ID: {chain_id})")
    print(f"RPC:        {rpc_url}")
    print(f"Deployer:   {account.address}")
    print(f"Balance:    {w3.from_wei(balance, 'ether')} ETH")

    if balance == 0:
        print("ERROR: Wallet has no ETH for gas")
        sys.exit(1)

    abi, bytecode = compile_contract()
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    # Estimate gas
    try:
        gas_estimate = w3.eth.estimate_gas({
            "from": account.address,
            "data": bytecode,
            "gasPrice": w3.eth.gas_price,
        })
        gas_limit = int(gas_estimate * 1.3)
    except Exception:
        gas_limit = 2000000

    nonce = w3.eth.get_transaction_count(account.address, "pending")
    base_fee = w3.eth.get_block("latest")["baseFeePerGas"]
    priority_fee = max(1000, w3.eth.max_priority_fee)
    max_fee = int(base_fee * 2) + priority_fee

    tx = contract.constructor().build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gas": gas_limit,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee,
        "chainId": chain_id,
        "type": 2,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"\nTx sent:    {tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    print(f"Status:     {'✅ SUCCESS' if receipt['status'] == 1 else '❌ FAILED'}")
    print(f"Gas used:   {receipt['gasUsed']}")
    print(f"Cost:       {w3.from_wei(receipt['gasUsed'] * receipt['effectiveGasPrice'], 'ether')} ETH")

    if receipt["status"] == 1:
        addr = receipt["contractAddress"]
        print(f"\nContract:   {addr}")
        print(f"Explorer:   {explorer}/address/{addr}")

        # Save deployment record
        record = {
            "chain": chain_key,
            "chainId": chain_id,
            "contractAddress": addr,
            "deployer": account.address,
            "txHash": tx_hash.hex(),
            "blockNumber": receipt["blockNumber"],
            "gasUsed": receipt["gasUsed"],
        }
        record_path = Path(__file__).parent.parent / "contracts" / "deployment.json"
        with open(record_path, "w") as f:
            json.dump(record, f, indent=2)
        print(f"\n✅ Deployment record saved: {record_path}")
        print(f"\nNext: Update 'contractAddress' in soulchain.config.json")
        return addr
    else:
        print("❌ Deployment failed")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy SoulRegistry to EVM chain")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--chain", choices=list(CHAINS.keys()))
    group.add_argument("--rpc-url", help="Custom RPC URL")
    parser.add_argument("--chain-id", type=int, default=8453, help="Chain ID (with --rpc-url)")
    parser.add_argument("--private-key", required=True, help="Deployer private key")
    args = parser.parse_args()

    if args.chain:
        chain = CHAINS[args.chain]
        deploy(args.chain, chain["rpc_url"], chain["chain_id"], chain["explorer"], args.private_key)
    else:
        explorer = f"https://basescan.org"  # default
        deploy("custom", args.rpc_url, args.chain_id, explorer, args.private_key)
