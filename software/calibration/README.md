# Calibration Files

## Layout

```
calibration/
  mac/
    teleoperators/so101_leader/
      leader_arm_1.json   ← right leader arm calibration
      leader_arm_2.json   ← left  leader arm calibration
  jetson/
    robots/xlerobot/
      my_xlerobot_pc.json ← merged bimanual follower calibration (left + right arms)
```

## Arm assignment

| Physical arm | Calibration file | Bus on Jetson |
|---|---|---|
| Left  follower | follower_arm_2 (merged as `left_arm_*`)  | Bus1 `/dev/ttyACM0` |
| Right follower | follower_arm_1 (merged as `right_arm_*`) | Bus2 `/dev/ttyACM1` |
| Left  leader   | `leader_arm_2.json`                       | Mac USB |
| Right leader   | `leader_arm_1.json`                       | Mac USB |

---

## Mac setup (one-time)

The leader calibration files are already on your Mac at:
```
~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/
```
Nothing to do — they were created when you originally calibrated the leader arms.

If you set up a new Mac, copy from this repo:
```bash
mkdir -p ~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/
cp calibration/mac/teleoperators/so101_leader/*.json \
   ~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/
```

---

## Jetson setup (one-time after git clone)

Copy the merged XLeRobot calibration file to the expected location:
```bash
mkdir -p ~/.cache/huggingface/lerobot/calibration/robots/xlerobot/
cp ~/XLeRobot/software/calibration/jetson/robots/xlerobot/my_xlerobot_pc.json \
   ~/.cache/huggingface/lerobot/calibration/robots/xlerobot/my_xlerobot_pc.json
```

When you run `xlerobot_host.py` for the first time, it will find this file and ask:
```
Press ENTER to restore calibration from file, or type 'c' to run manual calibration:
```
Press **ENTER** to use the saved calibration.

---

## Head motors and base wheels

`head_motor_1`, `head_motor_2`, `base_left_wheel`, `base_back_wheel`, `base_right_wheel`
are set to `null` in `my_xlerobot_pc.json` — they were not part of the original
individual SO101 calibration runs.

On first Jetson run, if the host prompts for calibration on these motors, type `c`
to run fresh calibration for just those motors. The arm calibration will be preserved.
