# XLeRobot Bimanual Remote Teleop

This is a fork of [Vector-Wangel/XLeRobot](https://github.com/Vector-Wangel/XLeRobot)
with additions for WiFi-based bimanual teleoperation and robot learning data collection.

---

## What this fork adds

The original XLeRobot repo already had ZMQ-based remote control infrastructure
(`xlerobot_host.py`, `xlerobot_client.py`). This fork builds on that to support:

- Two SO101 leader arms on a MacBook Pro sending commands over WiFi to the Jetson
- Dataset recording in LeRobot format for training VLA policies
- VLA inference mode with human intervention (policy runs the robot, human can take over)
- Tailscale support for internet-based teleop (same code, different IP)

**New files added in this fork:**

| File | Purpose |
|------|---------|
| `software/examples/9_so101_bimanual_leader_wifi_teleop.py` | Main Mac-side teleop script |
| `software/examples/JETSON_SETUP.md` | Step-by-step Jetson setup guide |
| `software/calibration/README.md` | Calibration file guide |
| `software/calibration/jetson/robots/xlerobot/my_xlerobot_pc.json` | Merged follower arm calibration for Jetson |
| `software/calibration/mac/teleoperators/so101_leader/` | Leader arm calibration files (for new Mac setup) |

**Modified files:**

| File | What changed |
|------|-------------|
| `software/src/robots/xlerobot/config_xlerobot.py` | Enabled 3 USB cameras (front, left_wrist, right_wrist), bumped host loop to 50Hz |

---

## Hardware

```
MacBook Pro                          Jetson AGX Orin 64GB
─────────────────                    ──────────────────────────────────
USB ── SO101 Leader Left  (arm 2)    Bus1 /dev/ttyACM0 ── SO101 Follower Left  (arm 2)
USB ── SO101 Leader Right (arm 1)    Bus2 /dev/ttyACM1 ── SO101 Follower Right (arm 1)
                                     USB ── Front camera
                                     USB ── Left wrist camera
                                     USB ── Right wrist camera
        │                                        │
        └──────────── WiFi / Tailscale ──────────┘
```

**Arm assignment:**
- Left arm = follower_arm_2 calibration, leader_arm_2 calibration
- Right arm = follower_arm_1 calibration, leader_arm_1 calibration

---

## Architecture

```
MAC (teleop computer)                JETSON (robot computer)
─────────────────────                ──────────────────────
9_so101_bimanual_leader_teleop.py    xlerobot_host.py
│                                    │
│  reads 2x SO101 leader joints      │  receives joint commands
│  50Hz via USB serial               │  writes to follower arms 50Hz
│                                    │
│──── ZMQ PUSH port 5555 ──────────►│  ZMQ PULL (commands in)
│◄─── ZMQ PULL port 5556 ────────────│  ZMQ PUSH (observations out)
│                                    │   └─ 12 joint positions
│  receives:                         │   └─ 3 camera frames (JPEG)
│  └─ follower joint state           │
│  └─ 3 camera frames                │  xlerobot_host.py runs:
│  displays cameras (OpenCV)         │  - XLerobot (both arms + base)
│                                    │  - camera capture
│  R key → record episode            │  - ZMQ server
│  V key → VLA inference mode        │
│  Q/ESC → quit                      │
```

---

## Jetson side — what to run

Everything the Jetson needs to do is handled by the **existing** `xlerobot_host.py`.
No new scripts needed on the Jetson.

**One-time setup** (after git clone):
```bash
# 1. Copy calibration file
mkdir -p ~/.cache/huggingface/lerobot/calibration/robots/xlerobot/
cp software/calibration/jetson/robots/xlerobot/my_xlerobot_pc.json \
   ~/.cache/huggingface/lerobot/calibration/robots/xlerobot/my_xlerobot_pc.json

# 2. Find camera paths (plug in all 3 USB cameras first)
ls /dev/video*
# Update config_xlerobot.py if your paths differ from /dev/video0,2,4

# 3. Find motor bus paths
ls /dev/ttyACM*
# Defaults are /dev/ttyACM0 (left arm + head) and /dev/ttyACM1 (right arm + base)
```

**Run the host:**
```bash
cd ~/XLeRobot
source ~/robotics_env/bin/activate   # or your venv
python software/src/robots/xlerobot/xlerobot_host.py
```

When prompted: press **Enter** to load calibration from file (arms are pre-calibrated).
Head motors and base wheels will need fresh calibration on first run — type `c` when
prompted for those specifically.

---

## Mac side — what to run

**One-time setup:**
```bash
# Edit the config section at the top of the teleop script
nano software/examples/9_so101_bimanual_leader_wifi_teleop.py

# Set these three values:
JETSON_IP         = "192.168.x.x"          # Jetson's WiFi IP (run `ip addr` on Jetson)
LEFT_LEADER_PORT  = "/dev/tty.usbserial-XX" # plug in left leader, run: ls /dev/tty.usb*
RIGHT_LEADER_PORT = "/dev/tty.usbserial-YY" # plug in right leader, run: ls /dev/tty.usb*
```

**Run teleop:**
```bash
# Make sure Jetson is already running xlerobot_host.py first
source /path/to/robotics_env/bin/activate
python software/examples/9_so101_bimanual_leader_wifi_teleop.py
```

---

## Data collection

When recording is active (`R` key), the Mac saves episodes in
[LeRobot dataset format](https://github.com/huggingface/lerobot) locally, then
optionally pushes to HuggingFace Hub.

Each timestep captures:
- `action` — 12 leader joint positions (what you commanded)
- `observation.state` — 12 follower joint positions (what the robot actually did)
- `observation.images.front` — front camera frame
- `observation.images.left_wrist` — left wrist camera frame
- `observation.images.right_wrist` — right wrist camera frame

This format is directly compatible with **pi0**, **pi0.5**, **SmolVLA** training.
For **Groot N1.5**, a format conversion step is needed (Isaac Lab format).

---

## VLA inference + intervention

Press `V` to toggle VLA mode. When active:
- A loaded policy generates joint commands from the current observation
- If a leader arm moves more than 3° in a single step, the system detects human
  intervention and uses the leader positions instead of the policy output
- All timesteps are recorded including interventions (useful for DAgger-style
  policy improvement)

To load an actual policy, edit `VLAPolicy.load()` in the teleop script.
The stub is already wired in — just replace the `select_action()` body.

---

## Internet access (Tailscale)

For teleop over the internet instead of local WiFi:

```bash
# Install on both Mac and Jetson
curl -fsSL https://tailscale.com/install.sh | sh   # Jetson
# Mac: download from https://tailscale.com/download

sudo tailscale up   # on Jetson
tailscale ip -4     # get Jetson's Tailscale IP (100.x.x.x)
```

Then in the Mac teleop script, set `JETSON_IP = "100.x.x.x"`. No other changes needed.

---

## Latency (WiFi LAN)

| Path | Breakdown | Total |
|------|-----------|-------|
| Commands Mac → Jetson → motors | serial read ~2ms + ZMQ ~2ms + motor write ~2ms | ~6ms |
| Camera Jetson → Mac | capture ~5ms + encode ~3ms + ZMQ ~5ms + decode ~2ms | ~15ms |

Over Tailscale (internet, same country): add ~10–20ms to both paths.
