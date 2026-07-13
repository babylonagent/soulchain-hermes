# SoulChain for Hermes

> **Identity that survives destruction.** Sovereign AI memory, anchored on-chain.
>
> Native Hermes Agent port of [openClause/soulchain](https://github.com/openClause/soulchain).

## What is this?

SoulChain anchors your Hermes Agent's identity and memory onto any EVM chain. Every tracked file (SOUL.md, MEMORY.md, USER.md) gets a tamper-proof cryptographic record on-chain. You can verify nothing was silently altered, and restore from any point in history.

When a VPS dies, a disk corrupts, or a provider shuts down — the agent's soul survives.

**Chain-agnostic by design.** Works on Base, Arbitrum, Optimism, Polygon, Ethereum, or any EVM network. Babylon Agent's deployment runs on Base L2, but you can deploy your own SoulRegistry contract anywhere in one command.

## Status: Phase 4 — ✅ PyPI Published

| Component | Status |
|---|---|
| SoulRegistry.sol | ✅ Deployed on Base (deploy your own on any chain) |
| `on-write` daemon | ✅ Watchdog file watcher — anchors within 2s of change |
| `interval` daemon | ✅ Periodic batch sync — configurable interval |
| `manual` CLI | ✅ On-demand anchor, status, verify |
| Encryption layer | ✅ Ed25519 + AES-256-GCM + argon2id keystore |
| Access grants | ✅ Grant/revoke read access per doc type |
| Multi-agent hierarchy | ✅ Parent/child registration on-chain |
| Restore from chain | ✅ Download + decrypt + verify hash |
| **PyPI package** | ✅ `pip install soulchain-hermes` |
| **`soulchain init`** | ✅ Interactive first-time setup |

### Proven test results

All three sync modes verified with real on-chain transactions on Base mainnet (works on any EVM chain):

| Mode | Test | Result |
|---|---|---|
| `on-write` | Appended to MEMORY.md → auto-anchored in ~7s | ✅ v0→v1 |
| `interval` | Appended to USER.md → picked up in 10s cycle | ✅ v0→v1 |
| `manual` | `soulchain anchor` → skips unchanged, anchors diffs | ✅ Working |
| Encryption | Daemon auto-encrypts with AES-256-GCM before anchoring | ✅ Encrypted blobs in storage |
| Restore | `soulchain restore --doc-type 0` → downloads, decrypts, verifies hash | ✅ Working |

## Quick Start

```bash
# Install from PyPI
pip install soulchain-hermes

# Initialize (generates keystore + config)
soulchain init

# Set your wallet private key (Base recommended — cheapest gas)
export SOULCHAIN_PRIVATE_KEY=0x...

# Register on-chain (one-time, costs gas)
soulchain register

# Anchor your files
soulchain anchor                  # anchor changed files
soulchain anchor --status         # show on-chain status
soulchain anchor --verify         # verify local vs on-chain

# Daemon mode — continuous sync
soulchain start --mode on-write   # file watcher (anchors within 2s)
soulchain start --mode interval   # periodic (every 5 min by default)

# Access control
soulchain grant 0xABC... --doc-type 0   # grant SOUL read access to an address
soulchain revoke 0xABC... --doc-type 0  # revoke access

# Restore from chain
soulchain restore --doc-type 0           # restore latest SOUL.md
soulchain restore --doc-type 1 --output /tmp/memory.md  # restore to file

# Multi-agent hierarchy
soulchain hierarchy                      # show parent + children
soulchain hierarchy --register-child 0xDEF...  # register child agent
```

## Sync Modes

### `on-write` — Real-time file watcher
Uses `watchdog` to monitor tracked files. When a file changes:
1. Debounces for 2 seconds (waits for writes to settle)
2. SHA-256 hashes the new content
3. Signs with EIP-191
4. Anchors on-chain via `writeDocument()`

**Best for:** Always-on agents that need every memory change immortalized.

### `interval` — Periodic batch sync
Checks all tracked files every N seconds. Anchors any that changed since last cycle.

**Best for:** Lightweight setups, cron-like operation, lower gas usage.

### `manual` — On-demand
No daemon. Run when you want to anchor.

```bash
soulchain anchor              # anchor changed files
soulchain anchor --force      # re-anchor everything
soulchain anchor --file ~/.hermes/SOUL.md
soulchain anchor --status     # on-chain status
soulchain anchor --verify     # verify integrity
soulchain anchor --json       # machine-readable output
```

**Best for:** Scripts, CI/CD hooks, manual checkpoints.

## Configuration

`soulchain.config.json`:
```json
{
  "chain": {
    "rpcUrl": "https://mainnet.base.org",
    "chainId": 8453,
    "contractAddress": "0x2AE3F15CAD486226Af839ae8FB4BbA08428283A2"
  },
  "trackedFiles": {
    "SOUL":     { "docType": 0,  "path": "~/.hermes/SOUL.md" },
    "MEMORY":   { "docType": 1,  "path": "~/.hermes/memories/MEMORY.md" },
    "USER":     { "docType": 3,  "path": "~/.hermes/memories/USER.md" },
    "IDENTITY": { "docType": 10, "path": "~/.hermes/config.yaml" }
  },
  "syncMode": "on-write",
  "syncIntervalSec": 300,
  "debounceMs": 2000
}
```

## Architecture

```
 ┌──────────────────────────────────────────────────────────┐
 │                    soulchain.core                         │
 │  SoulChainEngine — hash, sign, anchor, verify, status     │
 │  (shared by all three modes)                              │
 └──────────────────────────────────────────────────────────┘
         ▲              ▲              ▲
         │              │              │
 ┌──────────────┐ ┌────────────┐ ┌──────────────┐
 │  on_write    │ │  interval  │ │   manual     │
 │  watchdog    │ │  timer     │ │   CLI        │
 │  daemon      │ │  daemon    │ │   one-shot   │
 └──────────────┘ └────────────┘ └──────────────┘
         │              │              │
         ▼              ▼              ▼
 ┌──────────────────────────────────────────────────────────┐
 │              SoulRegistry.sol on Base L2                   │
 │  registerSoul() · writeDocument() · verifyDocument()      │
 └──────────────────────────────────────────────────────────┘
```

## Systemd Deployment

```bash
sudo cp deploy/soulchain-on-write.service /etc/systemd/system/
sudo systemctl edit soulchain-on-write
# Add your private key:
# [Service]
# Environment=SOULCHAIN_PRIVATE_KEY=0x...

sudo systemctl daemon-reload
sudo systemctl enable --now soulchain-on-write
sudo journalctl -u soulchain-on-write -f
```

See [`deploy/README.md`](deploy/README.md) for interval mode setup.

## Deployment

**Contract:** `0x2AE3F15CAD486226Af839ae8FB4BbA08428283A2` (Base mainnet)
**Deploy Tx:** `0x6f6c2efdf03d689c308822d2cced41e2fb84a20d209193546294394819c1550e`

## Cost Analysis

| Operation | Gas | Cost (Base L2) |
|---|---|---|
| `registerSoul()` | ~50k | ~$0.0000003 |
| `writeDocument()` | ~100k | ~$0.0000007 |
| Daily (4 files, on-write) | ~400k | ~$0.000003 |
| **Monthly** | ~12M | **~$0.00008** |

Effectively free. Base L2 gas is ~0.005 gwei.

## Roadmap

### Phase 1 — POC ✅
- [x] Deploy SoulRegistry to Base
- [x] Hash + sign + anchor files
- [x] Verify on-chain

### Phase 2 — Sync Modes ✅
- [x] `on-write` daemon (watchdog file watcher)
- [x] `interval` daemon (periodic batch)
- [x] `manual` CLI (on-demand)
- [x] Unified CLI + config file
- [x] Systemd service files
- [x] Smart skip (only anchor changed files)

### Phase 3 — Advanced ✅
- [x] Encryption layer (Ed25519 + AES-256-GCM + argon2id keystore)
- [x] Encrypted blob storage (LocalStorage + Pinata IPFS adapter)
- [x] Hermes skill (auto-load, status in agent context)
- [x] Access grants (grant/revoke read access per doc type)
- [x] Multi-agent hierarchy (parent/child on-chain)
- [x] Public verification dashboard (docs, grants, hierarchy)
- [x] Restore from chain (download + decrypt + verify)

### Phase 4 — Distribution (next)
- [ ] npm/pip package publish
- [ ] Cross-agent verification API (verify any agent's soul)
- [ ] Version timeline UI (browse all versions of each doc)
- [ ] IPFS pinning service integration (auto-pin on anchor)

## Credit

Based on [openClause/soulchain](https://github.com/openClause/soulchain) (MIT License).
SoulRegistry.sol is used verbatim from the original project.

## License

MIT
