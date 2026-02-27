#!/usr/bin/env python3
"""
Bimanual SO101 Leader Arm WiFi Teleoperation for XLeRobot
=========================================================
Mac side: reads two SO101 leader arms via USB and streams commands to
the Jetson AGX Orin running xlerobot_host.py over WiFi (or Tailscale for internet).

Features:
  - Bimanual 12-DOF teleoperation (left + right SO101 leaders)
  - Live camera display (front, left wrist, right wrist)
  - LeRobot-format dataset recording (press R to toggle)
  - VLA inference mode with human intervention (press V to toggle)
  - Tailscale-compatible: swap JETSON_IP to Tailscale IP for internet use

Usage:
  1. On Jetson: python xlerobot_host.py
  2. On Mac:    python 9_so101_bimanual_leader_wifi_teleop.py

Controls:
  R       - Start / stop episode recording
  V       - Toggle VLA inference mode (requires a loaded policy)
  Q / ESC - Quit

Requirements (robotics_env):
  pip install pyzmq opencv-python
  lerobot must be installed in the same env (already done)
"""

import json
import logging
import queue
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Add lerobot to path (robotics_env already has it installed)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lerobot.teleoperators.so101_leader import SO101Leader
from lerobot.teleoperators.so101_leader.config_so101_leader import SO101LeaderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.utils import hw_to_dataset_features, build_dataset_frame
from lerobot.utils.constants import ACTION, OBS_STR

from robots.xlerobot.xlerobot_client import XLerobotClient
from robots.xlerobot.config_xlerobot import XLerobotClientConfig, xlerobot_cameras_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ===========================================================================
# CONFIGURATION — edit these before running
# ===========================================================================

# Jetson IP on your WiFi LAN (run `ip addr` on Jetson to find it)
# For internet via Tailscale, swap this to the Tailscale IP (100.x.x.x)
JETSON_IP = "192.168.1.XXX"   # <-- CHANGE THIS

# USB serial ports for the two SO101 leader arms on Mac
# Find with: ls /dev/tty.usbserial-* or ls /dev/tty.usbmodem*
LEFT_LEADER_PORT  = "/dev/tty.usbserial-LEFT"   # <-- CHANGE THIS
RIGHT_LEADER_PORT = "/dev/tty.usbserial-RIGHT"  # <-- CHANGE THIS

# Dataset settings (HuggingFace repo to push to, or set PUSH_TO_HUB=False)
DATASET_REPO  = "SangamChapagain1/xlerobot_bimanual_demo"
PUSH_TO_HUB   = False          # set True to push to HuggingFace Hub after session
EPISODE_LEN   = 300            # steps per episode at 30fps = 10 seconds
NR_EPISODES   = 50             # max episodes before auto-stop
TASK          = "bimanual task"  # describe the task for the dataset

# Control frequency
FPS = 30

# Intervention threshold for VLA mode:
# if any leader joint moves more than this (degrees) in one step, human override activates
INTERVENTION_THRESHOLD_DEG = 3.0

# VLA mode: set to True and provide a policy object to enable policy inference
VLA_ENABLED_AT_START = False

# ===========================================================================
# Joint name mappings (leader → xlerobot action dict keys)
# ===========================================================================
LEFT_JOINT_MAP = {
    "shoulder_pan":  "left_arm_shoulder_pan",
    "shoulder_lift": "left_arm_shoulder_lift",
    "elbow_flex":    "left_arm_elbow_flex",
    "wrist_flex":    "left_arm_wrist_flex",
    "wrist_roll":    "left_arm_wrist_roll",
    "gripper":       "left_arm_gripper",
}
RIGHT_JOINT_MAP = {
    "shoulder_pan":  "right_arm_shoulder_pan",
    "shoulder_lift": "right_arm_shoulder_lift",
    "elbow_flex":    "right_arm_elbow_flex",
    "wrist_flex":    "right_arm_wrist_flex",
    "wrist_roll":    "right_arm_wrist_roll",
    "gripper":       "right_arm_gripper",
}

# Action/state joint ordering (must match xlerobot_client._state_order)
BIMANUAL_JOINT_ORDER = [
    "left_arm_shoulder_pan.pos",  "left_arm_shoulder_lift.pos",
    "left_arm_elbow_flex.pos",    "left_arm_wrist_flex.pos",
    "left_arm_wrist_roll.pos",    "left_arm_gripper.pos",
    "right_arm_shoulder_pan.pos", "right_arm_shoulder_lift.pos",
    "right_arm_elbow_flex.pos",   "right_arm_wrist_flex.pos",
    "right_arm_wrist_roll.pos",   "right_arm_gripper.pos",
]


# ===========================================================================
# Leader arm reader
# ===========================================================================

def read_leaders(left_leader: SO101Leader, right_leader: SO101Leader) -> dict:
    """Read both leader arms and return a combined action dict with xlerobot key names."""
    left_raw  = left_leader.get_action()   # {"shoulder_pan.pos": val, ...}
    right_raw = right_leader.get_action()

    action = {}
    for motor, xlero_name in LEFT_JOINT_MAP.items():
        action[f"{xlero_name}.pos"] = left_raw.get(f"{motor}.pos", 0.0)
    for motor, xlero_name in RIGHT_JOINT_MAP.items():
        action[f"{xlero_name}.pos"] = right_raw.get(f"{motor}.pos", 0.0)

    return action


# ===========================================================================
# Dataset helpers (mirrors 8_vr_teleop_with_dataset_recording.py)
# ===========================================================================

def init_dataset(cameras_ft: dict) -> LeRobotDataset:
    features = {
        "action": {
            "dtype": "float32",
            "shape": (12,),
            "names": BIMANUAL_JOINT_ORDER,
        },
        "observation.state": {
            "dtype": "float32",
            "shape": (12,),
            "names": BIMANUAL_JOINT_ORDER,
        },
    }
    camera_features = hw_to_dataset_features(cameras_ft, OBS_STR)
    features = {**features, **camera_features}

    dataset = LeRobotDataset.create(
        repo_id=DATASET_REPO,
        root=f"dataset_{int(time.time())}",
        features=features,
        fps=FPS,
        image_writer_processes=4,
        image_writer_threads=4,
    )
    return dataset


def dataset_saving_worker(
    dataset: LeRobotDataset,
    frame_queue: queue.Queue,
    shutdown_event: threading.Event,
    saving_in_progress_event: threading.Event,
    task: str,
):
    """Background thread: drains frame_queue and saves to disk."""
    try:
        dataset.meta.update_chunk_settings(video_files_size_in_mb=0.001)
        frame_nr = 0
        episode = 0
        while not shutdown_event.is_set():
            try:
                lerobot_frame = frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            dataset.add_frame(lerobot_frame)
            frame_nr += 1

            if frame_nr >= EPISODE_LEN:
                logger.info(f"Episode {episode} complete — saving...")
                saving_in_progress_event.set()
                dataset.save_episode()
                dataset.image_writer.wait_until_done()
                saving_in_progress_event.clear()
                frame_nr = 0
                episode += 1
                logger.info(f"Starting episode {episode}...")
                if episode >= NR_EPISODES:
                    logger.info("Reached max episodes. Stopping.")
                    shutdown_event.set()
                    break

    except Exception as e:
        logger.error(f"Dataset saving worker error: {e}", exc_info=True)
    finally:
        if dataset:
            dataset.image_writer.wait_until_done()
            dataset.save_episode()
            if PUSH_TO_HUB:
                logger.info("Pushing dataset to HuggingFace Hub...")
                dataset.push_to_hub()
                logger.info(f"Dataset pushed to {DATASET_REPO}")


# ===========================================================================
# VLA inference stub
# ===========================================================================

class VLAPolicy:
    """
    Placeholder for a loaded VLA policy (pi0, SmolVLA, Groot N1.5, etc.).
    Replace select_action() with your actual policy inference call.

    Example for SmolVLA / pi0 via LeRobot:
        from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
        self.policy = SmolVLAPolicy.from_pretrained("YOUR_HF_REPO")

    Example for pi0:
        from lerobot.policies.pi0.modeling_pi0 import PI0Policy
        self.policy = PI0Policy.from_pretrained("lerobot/pi0")
    """

    def __init__(self):
        self.policy = None
        self._loaded = False

    def load(self, repo_id: str):
        logger.info(f"Loading policy from {repo_id} ...")
        # TODO: replace with actual policy load
        # from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
        # self.policy = SmolVLAPolicy.from_pretrained(repo_id)
        self._loaded = True
        logger.info("Policy loaded (stub — returns zeros).")

    def select_action(self, observation: dict) -> dict:
        """
        Given the current observation dict from XLerobotClient.get_observation(),
        return an action dict with the same keys as BIMANUAL_JOINT_ORDER.
        """
        if not self._loaded:
            return {}
        # TODO: replace stub with real inference
        # Example:
        # state = observation["observation.state"]
        # images = {k: observation[k] for k in observation if "image" in k or k in cameras}
        # action_np = self.policy.select_action({"observation.state": state, **images})
        # return {k: float(action_np[i]) for i, k in enumerate(BIMANUAL_JOINT_ORDER)}

        # Stub: hold current state
        return {k: observation.get(k, 0.0) for k in BIMANUAL_JOINT_ORDER}


# ===========================================================================
# Camera display helper
# ===========================================================================

def show_cameras(frames: dict, recording: bool, vla_mode: bool):
    """Display all available camera frames in one tiled OpenCV window."""
    panels = []
    for name, frame in frames.items():
        if frame is None:
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
        h, w = frame.shape[:2]
        display = cv2.resize(frame, (320, 240))
        # Label
        cv2.putText(display, name, (5, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        panels.append(display)

    if not panels:
        tile = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(tile, "No cameras", (80, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 2)
    else:
        tile = np.hstack(panels)

    # Status bar
    status_parts = []
    if recording:
        status_parts.append("REC")
    if vla_mode:
        status_parts.append("VLA")
    status = "  |  ".join(status_parts) if status_parts else "TELEOP"
    color = (0, 0, 220) if recording else (0, 200, 0)
    cv2.putText(tile, status, (tile.shape[1] - 120, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    cv2.imshow("XLeRobot Cameras", tile)


# ===========================================================================
# Main loop
# ===========================================================================

def main():
    logger.info("=" * 60)
    logger.info("XLeRobot Bimanual SO101 WiFi Teleop")
    logger.info("=" * 60)

    # ---- Validate config -----------------------------------------------
    if "XXX" in JETSON_IP:
        logger.error("Set JETSON_IP in the CONFIG section at the top of this file.")
        sys.exit(1)
    if "LEFT" in LEFT_LEADER_PORT or "RIGHT" in RIGHT_LEADER_PORT:
        logger.error("Set LEFT_LEADER_PORT and RIGHT_LEADER_PORT in the CONFIG section.")
        sys.exit(1)

    # ---- Connect leader arms -------------------------------------------
    logger.info(f"Connecting left  leader on {LEFT_LEADER_PORT}")
    left_leader = SO101Leader(SO101LeaderConfig(port=LEFT_LEADER_PORT, id="left_leader"))
    left_leader.connect(calibrate=True)

    logger.info(f"Connecting right leader on {RIGHT_LEADER_PORT}")
    right_leader = SO101Leader(SO101LeaderConfig(port=RIGHT_LEADER_PORT, id="right_leader"))
    right_leader.connect(calibrate=True)

    # ---- Connect to Jetson via ZMQ -------------------------------------
    logger.info(f"Connecting to Jetson at {JETSON_IP} ...")
    robot_config = XLerobotClientConfig(
        remote_ip=JETSON_IP,
        id="xlerobot_wifi_client",
        cameras=xlerobot_cameras_config(),
    )
    robot = XLerobotClient(robot_config)
    robot.connect()
    logger.info("Connected to Jetson.")

    # ---- Dataset setup -------------------------------------------------
    cameras_ft = robot._cameras_ft  # {name: (H, W, 3)}
    dataset: LeRobotDataset | None = None
    frame_queue: queue.Queue = queue.Queue()
    shutdown_event   = threading.Event()
    saving_event     = threading.Event()
    dataset_thread: threading.Thread | None = None

    # ---- VLA policy setup ----------------------------------------------
    vla_policy = VLAPolicy()
    # Uncomment to load a real policy:
    # vla_policy.load("SangamChapagain1/your-trained-policy")

    # ---- State variables -----------------------------------------------
    recording   = False
    vla_mode    = VLA_ENABLED_AT_START
    prev_leader_action: dict = {}

    logger.info("Ready! Controls:  R=record  V=VLA mode  Q/ESC=quit")

    try:
        while not shutdown_event.is_set():
            loop_start = time.perf_counter()

            # ---- Read leader arms --------------------------------------
            leader_action = read_leaders(left_leader, right_leader)

            # ---- VLA inference + intervention detection ----------------
            if vla_mode:
                observation = robot.get_observation()

                # Detect human intervention
                if prev_leader_action:
                    max_delta = max(
                        abs(leader_action[k] - prev_leader_action.get(k, leader_action[k]))
                        for k in leader_action
                    )
                    is_intervention = max_delta > INTERVENTION_THRESHOLD_DEG
                else:
                    is_intervention = False

                if is_intervention:
                    action_to_send = leader_action
                    logger.debug("Human intervention detected — using leader action.")
                else:
                    policy_action = vla_policy.select_action(observation)
                    action_to_send = policy_action if policy_action else leader_action
            else:
                action_to_send = leader_action
                observation = robot.get_observation()
                is_intervention = False

            prev_leader_action = leader_action.copy()

            # ---- Send action to robot ----------------------------------
            # Keep head and base at neutral (no keyboard/base control in this script)
            full_action = {
                **action_to_send,
                "head_motor_1.pos": 0.0,
                "head_motor_2.pos": 0.0,
                "x.vel": 0.0,
                "y.vel": 0.0,
                "theta.vel": 0.0,
            }
            robot.send_action(full_action)

            # ---- Camera display ----------------------------------------
            frames = {k: observation.get(k) for k in cameras_ft}
            show_cameras(frames, recording, vla_mode)

            # ---- Keyboard input ----------------------------------------
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):  # Q or ESC
                logger.info("Quit requested.")
                break

            elif key == ord("r"):
                if not recording:
                    logger.info("Recording started.")
                    recording = True
                    dataset = init_dataset(cameras_ft)
                    dataset_thread = threading.Thread(
                        target=dataset_saving_worker,
                        args=(dataset, frame_queue, shutdown_event, saving_event, TASK),
                        daemon=False,
                    )
                    dataset_thread.start()
                else:
                    logger.info("Recording stopped.")
                    recording = False

            elif key == ord("v"):
                vla_mode = not vla_mode
                logger.info(f"VLA mode: {'ON' if vla_mode else 'OFF'}")

            # ---- Record frame if active ---------------------------------
            if recording and dataset is not None and not saving_event.is_set():
                follower_state = observation.get("observation.state", np.zeros(12, dtype=np.float32))
                action_vec = np.array(
                    [action_to_send.get(k, 0.0) for k in BIMANUAL_JOINT_ORDER], dtype=np.float32
                )

                action_features = {
                    **{k: float(action_vec[i]) for i, k in enumerate(BIMANUAL_JOINT_ORDER)},
                }
                obs_features = {
                    **{k: float(follower_state[i]) for i, k in enumerate(BIMANUAL_JOINT_ORDER)},
                    **{k: frames[k] for k in frames if frames[k] is not None},
                }

                action_frame = build_dataset_frame(dataset.features, action_features, prefix=ACTION)
                obs_frame    = build_dataset_frame(dataset.features, obs_features,    prefix=OBS_STR)
                lerobot_frame = {
                    **obs_frame,
                    **action_frame,
                    "task": TASK,
                }
                if vla_mode:
                    lerobot_frame["is_intervention"] = is_intervention

                frame_queue.put(lerobot_frame)

            # ---- Pace to FPS -------------------------------------------
            elapsed = time.perf_counter() - loop_start
            sleep_time = max(0.0, 1.0 / FPS - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — shutting down.")
    finally:
        shutdown_event.set()
        cv2.destroyAllWindows()

        if dataset_thread and dataset_thread.is_alive():
            logger.info("Waiting for dataset thread to finish...")
            dataset_thread.join()

        robot.disconnect()
        left_leader.disconnect()
        right_leader.disconnect()
        logger.info("Clean shutdown.")


if __name__ == "__main__":
    main()
