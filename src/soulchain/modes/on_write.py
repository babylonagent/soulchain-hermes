"""
SoulChain on-write mode — watches tracked files and anchors on change.

Uses watchdog to monitor file system events. When a tracked file is modified,
it debounces (waits for writes to settle), then anchors the new version.

Run as a daemon:
    python -m soulchain.modes.on_write

Or via systemd service.
"""
import logging
import os
import signal
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..core import SoulChainEngine, load_config, load_private_key

logger = logging.getLogger("soulchain.on_write")


class SoulChainHandler(FileSystemEventHandler):
    """Watches for file changes and triggers anchoring."""

    def __init__(self, engine: SoulChainEngine, config: dict):
        self.engine = engine
        self.config = config
        self.debounce_ms = config.get("debounceMs", 2000)
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._shutdown = False

        # Build reverse lookup: absolute path → (doc_type, name)
        self.watch_map: dict[str, tuple[int, str]] = {}
        for name, info in config["trackedFiles"].items():
            abs_path = str(Path(info["path"]).expanduser().resolve())
            self.watch_map[abs_path] = (info["docType"], name)
            logger.info(f"Tracking: {abs_path} → {name} (type {info['docType']})")

    def on_modified(self, event):
        if event.is_directory or self._shutdown:
            return
        self._handle_change(event.src_path)

    def on_created(self, event):
        if event.is_directory or self._shutdown:
            return
        self._handle_change(event.src_path)

    def _handle_change(self, filepath: str):
        """Debounce file changes, then anchor."""
        abs_path = str(Path(filepath).resolve())
        if abs_path not in self.watch_map:
            return

        doc_type, name = self.watch_map[abs_path]

        with self._lock:
            # Cancel existing timer for this file
            if abs_path in self._timers:
                self._timers[abs_path].cancel()

            # Set new timer
            timer = threading.Timer(
                self.debounce_ms / 1000,
                self._anchor_after_debounce,
                args=[abs_path, doc_type, name],
            )
            timer.daemon = True
            self._timers[abs_path] = timer
            timer.start()
            logger.debug(f"Debounced {name}: will anchor in {self.debounce_ms}ms")

    def _anchor_after_debounce(self, abs_path: str, doc_type: int, name: str):
        """Called after debounce timer fires."""
        if self._shutdown:
            return

        with self._lock:
            self._timers.pop(abs_path, None)

        logger.info(f"📝 {name} changed — anchoring...")
        try:
            tx_hash = self.engine.anchor_file(abs_path, doc_type)
            if tx_hash:
                logger.info(f"✅ {name} anchored: {tx_hash[:16]}...")
            else:
                logger.info(f"⏭️  {name}: no change or skipped")
        except Exception as e:
            logger.error(f"❌ {name} anchor failed: {e}")

    def flush(self):
        """Wait for pending debounced anchors to complete."""
        with self._lock:
            timers = list(self._timers.values())
        for t in timers:
            t.join(timeout=10)

    def shutdown(self):
        """Cancel all pending timers."""
        self._shutdown = True
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()


def run_daemon():
    """Run the on-write watcher daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [soulchain] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
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
        else:
            logger.warning(f"Keystore found at {keystore_path} but no SOULCHAIN_KEYSTORE_PASSWORD set")
    else:
        logger.info("Crypto: disabled (no keystore — plaintext anchoring only)")

    engine = SoulChainEngine(private_key, config=config, crypto=crypto)

    logger.info(f"SoulChain on-write daemon starting")
    logger.info(f"Agent: {engine.address}")
    logger.info(f"Balance: {engine.balance:.8f} ETH")

    if not engine.is_registered():
        logger.info("Registering soul...")
        engine.register_soul()

    handler = SoulChainHandler(engine, config)

    # Set up watchdog observers for each tracked file's directory
    observer = Observer()
    watched_dirs: set[str] = set()
    for name, info in config["trackedFiles"].items():
        filepath = Path(info["path"]).expanduser()
        watch_dir = str(filepath.parent.resolve())
        if watch_dir not in watched_dirs and filepath.parent.exists():
            observer.schedule(handler, watch_dir, recursive=False)
            watched_dirs.add(watch_dir)
            logger.info(f"Watching dir: {watch_dir}")

    observer.start()
    logger.info(f"On-write mode active. Monitoring {len(watched_dirs)} directories.")

    # Handle graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum} — shutting down...")
        handler.shutdown()
        handler.flush()
        observer.stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        while observer.is_alive():
            observer.join(1)
    finally:
        observer.join(timeout=5)
        handler.shutdown()
        logger.info("SoulChain daemon stopped")


if __name__ == "__main__":
    run_daemon()
