# SoulChain systemd deployment

## Install service

```bash
# Copy service files
sudo cp deploy/soulchain-on-write.service /etc/systemd/system/
sudo cp deploy/soulchain-interval.service /etc/systemd/system/

# Set private key in environment file
sudo systemctl edit soulchain-on-write
# Add:
# [Service]
# Environment=SOULCHAIN_PRIVATE_KEY=0x...

# Reload and start
sudo systemctl daemon-reload
sudo systemctl enable --now soulchain-on-write

# Check logs
sudo journalctl -u soulchain-on-write -f
```

## Switch modes

```bash
# Stop on-write, start interval
sudo systemctl stop soulchain-on-write
sudo systemctl start soulchain-interval

# Or use manual mode only (no daemon needed)
soulchain anchor
```
