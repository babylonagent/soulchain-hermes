# SoulChain for Hermes — Installation Guide

## Prerequisites

- Python 3.11+
- A funded EVM wallet (Base recommended — cheapest gas)
- Hermes Agent (or any file-based agent system)

## Quick Install

```bash
pip install soulchain-hermes
```

## Initial Setup

### 1. Initialize SoulChain

```bash
soulchain init
```

This will:
- Generate an Ed25519 keypair for encryption + signing
- Create an encrypted keystore at `~/.soulchain/keystore.json`
- Create a config file at `~/soulchain.config.json`
- You'll choose a passphrase — **don't lose it**

### 2. Set your wallet private key

SoulChain needs an EVM wallet to pay for on-chain transactions.

```bash
export SOULCHAIN_PRIVATE_KEY=0x...
```

Or use a wallet file:
```bash
export SOULCHAIN_PRIVATE_KEY_FILE=/path/to/wallet.env
```

### 3. Register your soul (one-time)

```bash
soulchain register
```

This calls `registerSoul()` on the SoulRegistry contract — your identity is now on Base.

### 4. Start anchoring

```bash
# Manual (one-shot)
soulchain anchor

# Daemon (continuous)
soulchain start --mode on-write    # real-time file watcher
soulchain start --mode interval    # periodic batch sync
```

## Using a Different Contract

The default contract (`0x2AE3F15C...`) is Babylon Agent's deployment. You can deploy your own:

```bash
pip install soulchain-hermes[deploy]
python scripts/deploy.py --chain base --private-key 0x...

# Update ~/soulchain.config.json → contractAddress to your new address
```

## Using Different Chains

Edit `~/soulchain.config.json`:

```json
{
  "chain": {
    "rpcUrl": "https://arbitrum-one-rpc.com",
    "chainId": 42161
  }
}
```

Supported: Base, Arbitrum, Optimism, Polygon, Ethereum, or any EVM chain.

## Using IPFS Storage (instead of local)

1. Get Pinata API keys at [pinata.cloud](https://pinata.cloud)
2. Configure in `~/soulchain.config.json`:

```json
{
  "storage": "pinata",
  "pinataApiKey": "",
  "pinataSecretKey": ""
}
```

Or via environment:
```bash
export PINATA_API_KEY=...
export PINATA_SECRET_KEY=...
```

## Systemd Service

```bash
# Copy template
sudo cp deploy/soulchain-on-write.service /etc/systemd/system/

# Add your private key
sudo systemctl edit soulchain-on-write
# Add:
# [Service]
# Environment=SOULCHAIN_PRIVATE_KEY=0x...
# Environment=SOULCHAIN_KEYSTORE_PASSWORD=your_passphrase

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now soulchain-on-write

# Watch logs
journalctl -u soulchain-on-write -f
```

## Verification Dashboard

The dashboard is a standalone HTML file — no backend needed:

```bash
cd dashboard
python3 -m http.server 8080
# Open http://localhost:8080
```

To use your own agent address, edit `index.html`:
```javascript
const AGENT_ADDR = "0xYOUR_AGENT_ADDRESS";
```
