# Jetson AGX Orin Setup for Bimanual WiFi Teleop

This guide sets up the Jetson side for `9_so101_bimanual_leader_wifi_teleop.py`.

---

## 1. Clone your fork

```bash
git clone https://github.com/SangamChapagain1/XLeRobot.git
cd XLeRobot/software
```

## 2. Install dependencies

```bash
# Create a venv (robotics_env)
python3 -m venv ~/robotics_env
source ~/robotics_env/bin/activate

# Install lerobot (the xlerobot software depends on it)
pip install -e ".[feetech]"    # if pyproject.toml is present
# OR
pip install pyzmq opencv-python numpy

# Install lerobot from the lerobot directory if needed:
# cd /path/to/lerobot && pip install -e .
```

## 3. Find your camera /dev/video* path

Plug in the front camera, then:

```bash
ls /dev/video*
v4l2-ctl --list-devices
```

Typical output:
```
/dev/video0   <- front / head camera
```

USB cameras usually appear on **even** indices. Odd indices (video1, video3) are
metadata streams — skip those.

Update `config_xlerobot.py` → `xlerobot_cameras_config()` with the correct path.
This fork uses front camera only by default.

## 4. Find your motor bus ports

```bash
ls /dev/ttyACM*
```

Expected:
- `/dev/ttyACM0`  — Bus 1 (left arm + head motors)
- `/dev/ttyACM1`  — Bus 2 (right arm + base motors)

These are already set as defaults in `config_xlerobot.py`. If yours are different,
update `port1` and `port2` in `XLerobotConfig`.

## 5. Find the Jetson's WiFi IP

```bash
ip addr show   # look for the wlan0 or wifi interface
# OR
hostname -I
```

Give this IP to the Mac side: set `JETSON_IP` in `9_so101_bimanual_leader_wifi_teleop.py`.

## 6. Run the host

```bash
source ~/robotics_env/bin/activate
cd XLeRobot/software
python -m src.robots.xlerobot.xlerobot_host
# OR if you have an entry point:
python src/robots/xlerobot/xlerobot_host.py
```

You should see:
```
Waiting for commands...
```

## 7. Internet access via Tailscale (optional)

Install Tailscale on **both** the Jetson and the Mac:

```bash
# Jetson
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Mac — download from https://tailscale.com/download
```

After connecting, get the Jetson's Tailscale IP:
```bash
tailscale ip -4
# e.g. 100.x.x.x
```

Set that as `JETSON_IP` in the Mac teleop script instead of the LAN IP.
No other code changes needed — ZMQ works transparently over Tailscale.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Camera not found | Run `v4l2-ctl --list-devices` and update `/dev/videoX` paths |
| Motor bus not found | Check `ls /dev/ttyACM*`, update `port1`/`port2` in config |
| ZMQ timeout on Mac | Check Jetson IP, firewall (`sudo ufw allow 5555,5556/tcp`), confirm host is running |
| High CPU on Jetson | Lower `max_loop_freq_hz` back to 30 in `XLerobotHostConfig` |
| VR script conflicts | The new teleop script is standalone — no VR hardware needed |
