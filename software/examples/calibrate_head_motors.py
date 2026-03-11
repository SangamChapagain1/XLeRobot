#!/usr/bin/env python3
"""
Standalone calibration for XLeRobot head motors (IDs 7, 8) on Bus 1.

Run this ON THE JETSON after you've:
  1. Changed head_motor_1 → ID 7 and head_motor_2 → ID 8 (setup_motor_ids.py)
  2. Connected both head motors to the LEFT ARM chain (Bus 1 / /dev/ttyACM0)

This script:
  - Connects to Bus 1 with ONLY the head motors
  - Guides you through position calibration (homing + range recording)
  - Merges the results into the existing xlerobot calibration JSON

Usage (on Jetson):
  cd ~/xlerobot/software
  python examples/calibrate_head_motors.py

  Or with a custom port:
  python examples/calibrate_head_motors.py --port /dev/ttyACM0
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode

CALIBRATION_DIR = Path(__file__).resolve().parents[1] / "calibration" / "jetson" / "robots" / "xlerobot"
CALIBRATION_FILE = CALIBRATION_DIR / "my_xlerobot_pc.json"

HEAD_MOTORS = {
    "head_motor_1": Motor(7, "sts3215", MotorNormMode.RANGE_M100_100),
    "head_motor_2": Motor(8, "sts3215", MotorNormMode.RANGE_M100_100),
}


def load_existing_calibration() -> dict:
    if CALIBRATION_FILE.is_file():
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    return {}


def save_merged_calibration(head_cal: dict[str, MotorCalibration]):
    existing = load_existing_calibration()

    for name, cal in head_cal.items():
        existing[name] = {
            "id": cal.id,
            "drive_mode": cal.drive_mode,
            "homing_offset": cal.homing_offset,
            "range_min": cal.range_min,
            "range_max": cal.range_max,
        }

    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(existing, f, indent=4)
    print(f"\nCalibration saved to {CALIBRATION_FILE}")


def run_calibration(port: str):
    print("=" * 60)
    print("  XLeRobot Head Motor Calibration")
    print("=" * 60)
    print(f"\n  Port : {port}")
    print("  Motors: head_motor_1 (ID 7), head_motor_2 (ID 8)")
    print("  Bus  : 1 (same chain as left arm)")
    print()

    bus = FeetechMotorsBus(port=port, motors=HEAD_MOTORS)

    try:
        bus.connect(handshake=False)
    except Exception as e:
        print(f"ERROR connecting to {port}: {e}")
        print("\nTroubleshooting:")
        print("  - Is the driver board plugged in and powered?")
        print("  - Are head motors connected to the LEFT ARM chain?")
        print("  - Did you set motor IDs to 7 and 8?")
        print("  - Try:  ls /dev/ttyACM*")
        sys.exit(1)

    print("Connected to bus.\n")

    motor_names = list(HEAD_MOTORS.keys())

    print("Step 1: Disable torque and set position mode...")
    bus.disable_torque()
    for name in motor_names:
        bus.write("Operating_Mode", name, OperatingMode.POSITION.value)
    print("  Done.\n")

    print("Step 2: Homing (center position)")
    print("  Manually move BOTH head motors to the CENTER of their range.")
    print("  (The position where the head looks straight ahead.)")
    input("  Press ENTER when centered...")
    homing_offsets = bus.set_half_turn_homings(motor_names)
    print(f"  Homing offsets: {homing_offsets}\n")

    print("Step 3: Range of motion recording")
    print("  Slowly move EACH head motor through its FULL range of motion.")
    print("  Move head_motor_1 (pan/tilt) all the way left and right (or up/down).")
    print("  Then move head_motor_2 through its full range.")
    print("  The script is recording the min/max positions continuously.")
    input("  Press ENTER to START recording...")
    range_mins, range_maxes = bus.record_ranges_of_motion(motor_names)
    print(f"  Range mins: {range_mins}")
    print(f"  Range maxes: {range_maxes}\n")

    calibration = {}
    for name in motor_names:
        motor = HEAD_MOTORS[name]
        calibration[name] = MotorCalibration(
            id=motor.id,
            drive_mode=0,
            homing_offset=homing_offsets[name],
            range_min=range_mins[name],
            range_max=range_maxes[name],
        )

    bus.write_calibration(calibration)
    print("Calibration written to motor EEPROM.\n")

    bus.disconnect()

    save_merged_calibration(calibration)

    print("\nCalibration complete!")
    print("Head motor values have been merged into the existing calibration file.")
    print("Next time xlerobot_host.py runs, it will pick up these values automatically.")


def verify_motors(port: str):
    """Quick check that head motors respond on the bus."""
    print("=" * 60)
    print("  Verify Head Motors")
    print("=" * 60)
    print(f"\n  Scanning IDs 7 and 8 on {port}...")

    bus = FeetechMotorsBus(port=port, motors=HEAD_MOTORS)
    try:
        bus.connect(handshake=False)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    for name, motor in HEAD_MOTORS.items():
        try:
            pos = bus._read(56, 2, motor.id)  # Present_Position register
            print(f"  {name} (ID {motor.id}): position = {pos}")
        except Exception as e:
            print(f"  {name} (ID {motor.id}): NOT RESPONDING — {e}")

    bus.disconnect()
    print()


def main():
    parser = argparse.ArgumentParser(description="Calibrate XLeRobot head motors")
    parser.add_argument(
        "--port", default="/dev/ttyACM0",
        help="Serial port for Bus 1 (default: /dev/ttyACM0)"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Just verify that head motors respond (no calibration)"
    )
    args = parser.parse_args()

    if args.verify:
        verify_motors(args.port)
    else:
        verify_motors(args.port)
        proceed = input("Proceed with calibration? [y/N]: ").strip().lower()
        if proceed == "y":
            run_calibration(args.port)
        else:
            print("Aborted.")


if __name__ == "__main__":
    main()
