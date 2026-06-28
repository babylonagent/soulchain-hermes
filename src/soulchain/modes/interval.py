"""
SoulChain interval mode — anchors changed files on a timer.

Checks all tracked files every N seconds and anchors any that changed.
Lighter weight than on-write (no file watcher overhead), good for periodic sync.

Run as a daemon:
    python -m soulchain.modes.interval

Or as a cron job:
    soulchain sync --mode interval
"""
import logging
import os
import signal
import time

from ..core import SoulChainEngine, load_config, load_private_key

logger = logging.getLogger("soulchain.interval")


def run_daemon():
    """Run the interval-based sync daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [soulchain] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    interval = config.get("syncIntervalSec", 300)
    private_key = load_private_key()

    # Load crypto provider if keystore exists
    crypto = None
    keystore_path = os.environ.get("SOULCHAIN_KEYSTORE", os.path.expanduser("~/.soulchain/keystore.json"))
    if os.path.exists(keystore_path):
        passphrase = os.environ.get("SOULCHAIN_KEYSTORE_PASSWORD")
        if passphrase:
            from ..crypto import SoulCryptoProvider
            crypto = SoulCryptoProvider.from_keystore(keystore_path, passphrase)
            logger.info(f"Crypto: enabled ({crypto.address})")

    engine = SoulChainEngine(private_key, config=config, crypto=crypto)

    logger.info(f"SoulChain interval daemon starting")
    logger.info(f"Agent: {engine.address}")
    logger.info(f"Balance: {engine.balance:.8f} ETH")
    logger.info(f"Interval: every {interval}s ({interval // 60}m {interval % 60}s)")

    if not engine.is_registered():
        logger.info("Registering soul...")
        engine.register_soul()

    # Handle graceful shutdown
    _shutdown = False

    def signal_handler(signum, frame):
        nonlocal _shutdown
        _shutdown = True
        logger.info(f"Received signal {signum} — shutting down after current cycle...")

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    cycle = 0
    while not _shutdown:
        cycle += 1
        logger.info(f"--- Sync cycle #{cycle} ---")

        try:
            results = engine.anchor_all()
            anchored = [r for r in results if r["status"] == "anchored"]
            unchanged = [r for r in results if r["status"] == "unchanged"]
            failed = [r for r in results if r["status"] == "failed"]

            if anchored:
                logger.info(f"Anchored {len(anchored)} file(s)")
            if unchanged:
                logger.debug(f"{len(unchanged)} file(s) unchanged")
            if failed:
                logger.warning(f"{len(failed)} file(s) failed to anchor")
        except Exception as e:
            logger.error(f"Sync cycle failed: {e}")

        # Sleep in small increments to allow shutdown signal
        for _ in range(interval):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("SoulChain interval daemon stopped")


if __name__ == "__main__":
    run_daemon()
