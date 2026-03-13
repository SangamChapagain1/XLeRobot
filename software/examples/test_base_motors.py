#!/usr/bin/env python3
"""
Test script for XLeRobot 3-wheel omnidirectional base.
Tests base motors (IDs 7, 8, 9) on Bus 2 (/dev/ttyACM0).
No arms, cameras, or calibration needed.

Usage:
    cd software
    python examples/test_base_motors.py

Controls (interactive mode):
    i/k  - Forward / Backward
    j/l  - Strafe Left / Right
    u/o  - Rotate Left / Right
    n/m  - Speed Up / Down
    SPACE - Emergency stop
    q    - Quit
"""

import sys
import time
import select
import termios
import tty
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode

PORT = "/dev/ttyACM0"

MOTORS = {
    "base_left_wheel":  Motor(7, "sts3215", MotorNormMode.RANGE_M100_100),
    "base_back_wheel":  Motor(8, "sts3215", MotorNormMode.RANGE_M100_100),
    "base_right_wheel": Motor(9, "sts3215", MotorNormMode.RANGE_M100_100),
}

SPEED_LEVELS = [
    {"xy": 0.15, "theta": 45, "label": "SLOW"},
    {"xy": 0.30, "theta": 90, "label": "MEDIUM"},
    {"xy": 0.50, "theta": 140, "label": "FAST"},
    {"xy": 0.75, "theta": 200, "label": "TURBO"},
]


def degps_to_raw(degps: float) -> int:
    steps_per_deg = 4096.0 / 360.0
    val = int(round(degps * steps_per_deg))
    return max(-0x7FFF, min(0x7FFF, val))


def body_to_wheel_raw(
    x: float, y: float, theta: float,
    wheel_radius: float = 0.05, base_radius: float = 0.125, max_raw: int = 3000,
) -> dict:
    theta_rad = theta * (np.pi / 180.0)
    velocity = np.array([x, y, theta_rad])
    angles = np.radians(np.array([240, 0, 120]) - 90)
    m = np.array([[np.cos(a), np.sin(a), base_radius] for a in angles])
    wheel_linear = m.dot(velocity)
    wheel_angular = wheel_linear / wheel_radius
    wheel_degps = wheel_angular * (180.0 / np.pi)

    steps_per_deg = 4096.0 / 360.0
    raw_floats = [abs(d) * steps_per_deg for d in wheel_degps]
    max_computed = max(raw_floats)
    if max_computed > max_raw:
        wheel_degps = wheel_degps * (max_raw / max_computed)

    return {
        "base_left_wheel":  degps_to_raw(wheel_degps[0]),
        "base_back_wheel":  degps_to_raw(wheel_degps[1]),
        "base_right_wheel": degps_to_raw(wheel_degps[2]),
    }


def get_key(timeout=0.05):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if rlist:
            return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return None


def scan_motors(bus):
    print("\n  Scanning for base motors on bus...")
    found = []
    for motor_name, motor in MOTORS.items():
        mid = motor.id
        try:
            val = bus._read(5, 1, mid)
            if val is not None:
                found.append((motor_name, mid))
                print(f"    {motor_name} (ID {mid}): FOUND")
            else:
                print(f"    {motor_name} (ID {mid}): no response")
        except Exception as e:
            print(f"    {motor_name} (ID {mid}): ERROR - {e}")
    return found


def test_individual_motors(bus):
    print("\n  Individual motor spin test (each motor spins briefly)...")
    speed = 300
    for motor_name in MOTORS:
        mid = MOTORS[motor_name].id
        print(f"    Spinning {motor_name} (ID {mid}) forward...", end="", flush=True)
        try:
            bus.sync_write("Goal_Velocity", {motor_name: speed})
            time.sleep(0.5)
            bus.sync_write("Goal_Velocity", {motor_name: 0})
            time.sleep(0.2)

            print(" reverse...", end="", flush=True)
            bus.sync_write("Goal_Velocity", {motor_name: -speed})
            time.sleep(0.5)
            bus.sync_write("Goal_Velocity", {motor_name: 0})
            print(" OK")
        except Exception as e:
            print(f" FAILED: {e}")

    print("  Individual motor test complete.")


def test_movements(bus):
    print("\n  Movement pattern test...")
    duration = 1.0
    patterns = [
        ("Forward",      0.10,  0.0,   0.0),
        ("Backward",    -0.10,  0.0,   0.0),
        ("Strafe Left",  0.0,   0.10,  0.0),
        ("Strafe Right", 0.0,  -0.10,  0.0),
        ("Rotate CW",   0.0,   0.0,  -40.0),
        ("Rotate CCW",  0.0,   0.0,   40.0),
    ]
    for name, x, y, theta in patterns:
        wheel_cmds = body_to_wheel_raw(x, y, theta)
        print(f"    {name:15s} -> L={wheel_cmds['base_left_wheel']:+5d}  "
              f"B={wheel_cmds['base_back_wheel']:+5d}  R={wheel_cmds['base_right_wheel']:+5d}",
              end="", flush=True)
        try:
            bus.sync_write("Goal_Velocity", wheel_cmds)
            time.sleep(duration)
            bus.sync_write("Goal_Velocity", dict.fromkeys(MOTORS, 0))
            time.sleep(0.3)
            print("  OK")
        except Exception as e:
            print(f"  FAILED: {e}")

    print("  Movement pattern test complete.")


def interactive_mode(bus):
    speed_idx = 0
    print("\n  ┌──────────────────────────────────────────┐")
    print("  │  INTERACTIVE BASE CONTROL                │")
    print("  │                                          │")
    print("  │  i/k  = Forward / Backward               │")
    print("  │  j/l  = Strafe Left / Right              │")
    print("  │  u/o  = Rotate Left / Right              │")
    print("  │  n/m  = Speed Up / Down                  │")
    print("  │  SPACE = Emergency Stop                  │")
    print("  │  q    = Quit                             │")
    print("  └──────────────────────────────────────────┘")
    print(f"  Speed: {SPEED_LEVELS[speed_idx]['label']}")

    try:
        while True:
            key = get_key(timeout=0.05)

            x_cmd = 0.0
            y_cmd = 0.0
            theta_cmd = 0.0

            if key == "q":
                bus.sync_write("Goal_Velocity", dict.fromkeys(MOTORS, 0))
                print("\n  Quit.")
                break
            elif key == " ":
                bus.sync_write("Goal_Velocity", dict.fromkeys(MOTORS, 0))
                print("\r  EMERGENCY STOP                              ", end="", flush=True)
                continue
            elif key == "n":
                speed_idx = min(speed_idx + 1, len(SPEED_LEVELS) - 1)
                print(f"\r  Speed: {SPEED_LEVELS[speed_idx]['label']}                    ", end="", flush=True)
                continue
            elif key == "m":
                speed_idx = max(speed_idx - 1, 0)
                print(f"\r  Speed: {SPEED_LEVELS[speed_idx]['label']}                    ", end="", flush=True)
                continue

            spd = SPEED_LEVELS[speed_idx]
            if key == "i":
                x_cmd = spd["xy"]
            elif key == "k":
                x_cmd = -spd["xy"]
            elif key == "j":
                y_cmd = spd["xy"]
            elif key == "l":
                y_cmd = -spd["xy"]
            elif key == "u":
                theta_cmd = spd["theta"]
            elif key == "o":
                theta_cmd = -spd["theta"]

            if x_cmd != 0 or y_cmd != 0 or theta_cmd != 0:
                wheel_cmds = body_to_wheel_raw(x_cmd, y_cmd, theta_cmd)
                bus.sync_write("Goal_Velocity", wheel_cmds)
                direction = []
                if x_cmd > 0: direction.append("FWD")
                elif x_cmd < 0: direction.append("BWD")
                if y_cmd > 0: direction.append("LEFT")
                elif y_cmd < 0: direction.append("RIGHT")
                if theta_cmd > 0: direction.append("ROT_L")
                elif theta_cmd < 0: direction.append("ROT_R")
                label = "+".join(direction)
                print(f"\r  {label:12s} L={wheel_cmds['base_left_wheel']:+5d} "
                      f"B={wheel_cmds['base_back_wheel']:+5d} "
                      f"R={wheel_cmds['base_right_wheel']:+5d}   ", end="", flush=True)
                time.sleep(0.15)
                bus.sync_write("Goal_Velocity", dict.fromkeys(MOTORS, 0))
            elif key is None:
                pass
    except KeyboardInterrupt:
        bus.sync_write("Goal_Velocity", dict.fromkeys(MOTORS, 0))
        print("\n  Interrupted.")


def main():
    print("=" * 60)
    print("XLeRobot Base Motor Test")
    print("=" * 60)
    print(f"Port: {PORT}")
    print(f"Motors: {', '.join(f'{n} (ID {m.id})' for n, m in MOTORS.items())}")

    bus = FeetechMotorsBus(port=PORT, motors=MOTORS)

    try:
        bus.connect(handshake=False)
    except Exception as e:
        print(f"\nFailed to open {PORT}: {e}")
        print("Check that the Feetech driver board is connected and powered.")
        sys.exit(1)

    print(f"Serial port {PORT} opened.")

    # Scan
    found = scan_motors(bus)
    if not found:
        print("\n  No motors found! Check:")
        print("    - External power supply to driver board (6-8V)")
        print("    - Motor wiring (daisy chain from driver board)")
        print("    - Motor IDs are set to 7, 8, 9")
        bus.port_handler.closePort()
        sys.exit(1)

    found_names = {name for name, _ in found}
    missing = set(MOTORS.keys()) - found_names
    if missing:
        print(f"\n  WARNING: Missing motors: {', '.join(missing)}")
        cont = input("  Continue anyway? [y/N]: ").strip().lower()
        if cont != "y":
            bus.port_handler.closePort()
            sys.exit(0)

    # Configure velocity mode
    print("\n  Setting motors to velocity mode...")
    try:
        for name in found_names:
            bus.write("Torque_Enable", name, 0)
        for name in found_names:
            bus.write("Operating_Mode", name, OperatingMode.VELOCITY.value)
        for name in found_names:
            bus.write("Torque_Enable", name, 1)
        print("  Velocity mode configured.")
    except Exception as e:
        print(f"  Failed to configure motors: {e}")
        bus.port_handler.closePort()
        sys.exit(1)

    # Menu
    while True:
        print("\n" + "-" * 40)
        print("Options:")
        print("  [1] Scan motors")
        print("  [2] Individual motor spin test")
        print("  [3] Movement pattern test (auto)")
        print("  [4] Interactive keyboard control")
        print("  [q] Quit")
        choice = input("Choice: ").strip().lower()

        if choice == "q":
            break
        elif choice == "1":
            scan_motors(bus)
        elif choice == "2":
            test_individual_motors(bus)
        elif choice == "3":
            test_movements(bus)
        elif choice == "4":
            interactive_mode(bus)
        else:
            print("Invalid choice.")

    # Cleanup
    print("\nStopping motors...")
    try:
        bus.sync_write("Goal_Velocity", dict.fromkeys(MOTORS, 0))
    except Exception:
        pass
    try:
        bus.disconnect(disable_torque=False)
    except Exception:
        try:
            bus.port_handler.closePort()
        except Exception:
            pass
    print("Done.")


if __name__ == "__main__":
    main()
