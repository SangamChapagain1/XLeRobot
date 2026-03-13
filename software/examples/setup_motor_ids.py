#!/usr/bin/env python3
"""
Change Feetech STS3215 servo motor IDs one at a time on macOS.

All new STS3215 motors ship with default ID=1. This script lets you
reprogram them to any target ID (7, 8, 9, etc.) using just a MacBook
and a single Feetech servo driver board.

HOW TO USE:
  1. Connect the driver board to your Mac via USB
  2. Find the port:  ls /dev/tty.usbmodem*
  3. Connect ONLY ONE motor to the driver board at a time
  4. Run:  python setup_motor_ids.py
  5. Follow the interactive prompts
  6. Repeat for each motor

The script will:
  - Detect the motor on the bus (default ID=1)
  - Disable torque and unlock EEPROM
  - Write the new ID you specify
  - Verify the change

This works on macOS, Linux, and Windows. No special tools needed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus


XLEROBOT_MOTOR_MAP = {
    "Bus 1 (left arm + head) — /dev/ttyACM1 on Jetson": {
        "head_motor_1": 7,
        "head_motor_2": 8,
    },
    "Bus 2 (right arm + base) — /dev/ttyACM0 on Jetson": {
        "base_left_wheel": 7,
        "base_back_wheel": 8,
        "base_right_wheel": 9,
    },
}


def find_serial_port() -> str:
    import glob
    candidates = glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    if not candidates:
        print("\nNo USB serial ports found.")
        print("Make sure the Feetech driver board is plugged in.")
        print("Run:  ls /dev/tty.usb*  or  ls /dev/ttyACM*")
        sys.exit(1)

    if len(candidates) == 1:
        print(f"\nFound serial port: {candidates[0]}")
        return candidates[0]

    print("\nMultiple serial ports found:")
    for i, p in enumerate(candidates):
        print(f"  [{i}] {p}")
    choice = input("Choose port number: ").strip()
    return candidates[int(choice)]


def safe_disconnect(bus):
    """Close the serial port without crashing if motors don't respond."""
    try:
        bus.disconnect(disable_torque=False)
    except Exception:
        try:
            bus.port_handler.closePort()
        except Exception:
            pass


def change_motor_id(port: str, current_id: int, target_id: int):
    bus = FeetechMotorsBus(
        port=port,
        motors={"motor": Motor(id=current_id, model="sts3215", norm_mode=MotorNormMode.RANGE_M100_100)},
    )
    bus.connect(handshake=False)

    try:
        print(f"\n  Disabling torque on motor ID {current_id}...")
        bus._disable_torque(current_id, "sts3215", num_retry=3)

        print(f"  Unlocking EEPROM on motor ID {current_id}...")
        bus._write(55, 1, current_id, 0, num_retry=3)

        print(f"  Writing new ID: {current_id} → {target_id}...")
        bus._write(5, 1, current_id, target_id, num_retry=3)

        print(f"  Verifying...")
        val = bus._read(5, 1, target_id)
        if val is not None:
            print(f"  Read back ID = {val} — SUCCESS")
        else:
            print(f"  Could not verify (this is sometimes normal).")
            print(f"  The ID change likely worked. Test by power-cycling the motor.")

        print(f"  Locking EEPROM on new ID {target_id}...")
        bus._write(55, 1, target_id, 1, num_retry=3)

    except Exception as e:
        print(f"  ERROR: {e}")
        print("  Make sure only ONE motor is connected and it's powered on.")
        print("  If the motor was already assigned an ID, use option [2] or [3] to scan first.")
    finally:
        safe_disconnect(bus)


def interactive_mode(port: str):
    print("\n" + "=" * 60)
    print("XLeRobot Motor ID Setup")
    print("=" * 60)
    print("\nMotors needed for XLeRobot:")
    for bus_label, motors in XLEROBOT_MOTOR_MAP.items():
        print(f"\n  {bus_label}:")
        for name, target_id in motors.items():
            print(f"    {name:20s} → ID {target_id}")

    print("\n" + "-" * 60)
    print("IMPORTANT: Connect only ONE motor at a time!")
    print("All new motors have default ID = 1")
    print("-" * 60)

    while True:
        print("\nOptions:")
        print("  [1] Change a motor ID (default ID 1 → target)")
        print("  [2] Change from a custom current ID → target")
        print("  [3] Scan for motors on the bus")
        print("  [q] Quit")

        choice = input("\nChoice: ").strip().lower()

        if choice == "q":
            print("Done.")
            break

        elif choice == "1":
            target = input("Target ID (e.g. 7, 8, or 9): ").strip()
            if not target.isdigit() or int(target) < 1 or int(target) > 253:
                print("Invalid ID. Must be 1-253.")
                continue
            target_id = int(target)
            input(f"\nConnect the motor you want to set to ID {target_id} and press Enter...")
            change_motor_id(port, current_id=1, target_id=target_id)

        elif choice == "2":
            current = input("Current motor ID: ").strip()
            target = input("Target motor ID: ").strip()
            if not current.isdigit() or not target.isdigit():
                print("Invalid input.")
                continue
            input(f"\nConnect the motor (currently ID {current}) and press Enter...")
            change_motor_id(port, current_id=int(current), target_id=int(target))

        elif choice == "3":
            print("\nScanning for motors (IDs 1-20)...")
            bus = FeetechMotorsBus(
                port=port,
                motors={"scan": Motor(id=1, model="sts3215", norm_mode=MotorNormMode.RANGE_M100_100)},
            )
            bus.connect(handshake=False)
            found = []
            for scan_id in range(1, 21):
                try:
                    val = bus._read(5, 1, scan_id)
                    if val is not None:
                        found.append(scan_id)
                        print(f"  Found motor at ID {scan_id}")
                except Exception:
                    pass
            safe_disconnect(bus)
            if not found:
                print("  No motors found. Check power and connections.")
            else:
                print(f"  Total found: {len(found)} motor(s)")

        else:
            print("Invalid choice.")


def main():
    port = find_serial_port()
    interactive_mode(port)


if __name__ == "__main__":
    main()
