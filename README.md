# SoulChain for Hermes

> **Identity that survives destruction.** Sovereign AI memory, anchored on-chain.
>
> Native Hermes Agent port of [openClause/soulchain](https://github.com/openClause/soulchain).

## What is this?

SoulChain anchors your Hermes Agent's identity and memory onto the Base blockchain. Every anchored file (SOUL.md, MEMORY.md, USER.md) gets a tamper-proof cryptographic record on-chain. You can verify nothing was silently altered, and restore from any point in history.

When a VPS dies, a disk corrupts, or a provider shuts down — the agent's soul survives.

## Status: Phase 1 (POC) — ✅ PROVEN

The end-to-end loop works:

```
[SOUL.md] → SHA-256 → EIP-191 sign → SoulRegistry.writeDocument() → Base L2 → verify
```

| Component | Status |
|---|---|
| SoulRegistry.sol | ✅ Deployed on Base mainnet |
| registerSoul() | ✅ Called, soul registered |
| writeDocument() | ✅ Anchored SOUL.md on-chain |
| verifyDocument() | ✅ Local hash matches on-chain hash |
| Python anchor script | ✅ Working |

## Deployment

**Contract:** `0x2AE3F15CAD486226Af839ae8FB4BbA08428283A2` (Base mainnet)
**Deployer:** `0x8741b8a825644D9Ef18Faf2DAB5e9b47B900F2b6`
**Deploy Tx:** `0x6f6c2efdf03d689c308822d2cced41e2fb84a20d209193546294394819c1550e`
**Register Tx:** `0x46a68db03f08b344227957fb08fb83300eefaf2f9a1f833c5ba239b84d04ffe6`
**First Anchor:** `0x2d105eaffd390bb88d8636a5552cb2a2f570b755ad9dcaea7c114abb53c28bc1`

## Quick Start

```bash
# Set up Python venv
python3.11 -m venv .venv
pip install web3 eth-account py-solc-x

# Deploy (if needed)
python scripts/deploy.py --chain base --private-key $PRIVATE_KEY

# Anchor all tracked files
export SOULCHAIN_PRIVATE_KEY=0x...
python scripts/anchor.py

# Check on-chain status
python scripts/anchor.py --status

# Verify local files match on-chain hashes
python scripts/anchor.py --verify
```

## Tracked Files

| File | Doc Type | Description |
|---|---|---|
| `~/.hermes/SOUL.md` | 0 (SOUL) | Agent identity / personality |
| `~/.hermes/memories/MEMORY.md` | 1 (MEMORY) | Agent persistent memory |
| `~/.hermes/memories/USER.md` | 3 (USER) | User profile |
| `~/.hermes/config.yaml` | 10 (IDENTITY) | Agent configuration |

## Architecture

```
Hermes Agent memory/skills files
         │
         ▼
  ┌──────────────┐
  │  anchor.py   │  ← hashes files with SHA-256
  │              │  ← signs with EIP-191 (deployer wallet)
  └──────┬───────┘
         │
         ▼
  ┌──────────────────────────────────────────┐
  │  SoulRegistry.sol on Base L2 (~$0.001)   │
  │  - registerSoul() — one-time identity    │
  │  - writeDocument() — anchor file version │
  │  - verifyDocument() — public tamper-check│
  │  - grantAccess() / revokeAccess()        │
  │  - registerChild() — multi-agent tree    │
  └──────────────────────────────────────────┘
```

## Roadmap

### Phase 1 — POC ✅
- [x] Deploy SoulRegistry to Base
- [x] Register soul
- [x] Hash + sign + anchor files
- [x] Verify on-chain
- [x] Status command

### Phase 2 — Native Skill (next)
- [ ] Hermes skill (SKILL.md) — auto-load on memory writes
- [ ] Encryption layer (Ed25519 + AES-256) — encrypted blobs to IPFS/Arweave
- [ ] Cron job — daily batch anchor
- [ ] Proper keystore (not raw private key in env)
- [ ] Funded dedicated signer wallet

### Phase 3 — Advanced
- [ ] Access grants — let other agents/people verify your identity
- [ ] Multi-agent hierarchy — parent/child agent relationships on-chain
- [ ] Public anchoring dashboard
- [ ] File restore from on-chain history

## Cost Analysis

| Operation | Gas | Cost (Base L2) |
|---|---|---|
| Deploy SoulRegistry | ~1,534,635 | ~$0.000010 |
| registerSoul() | ~50,000 | ~$0.0000003 |
| writeDocument() | ~250,000 | ~$0.0000017 |
| Daily anchor (4 files) | ~1,000,000 | ~$0.000007 |
| **Monthly total** | ~30M | **~$0.0002** |

Base L2 is absurdly cheap. Anchoring all tracked files daily costs fractions of a cent.

## Credit

Based on [openClause/soulchain](https://github.com/openClause/soulchain) (MIT License).
SoulRegistry.sol is used verbatim from the original project.

## License

MIT
