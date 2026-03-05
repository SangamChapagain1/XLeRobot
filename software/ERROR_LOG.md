# XLeRobot Error Log

Use this file to track reproducible errors and fixes across Jetson and Mac.

## 2026-03-04 - Jetson host import error
- **Context**: Running `python src/robots/xlerobot/xlerobot_host.py` directly.
- **Error**: `ImportError: attempted relative import with no known parent package`
- **Fix**: Run as module from `software/`:
  - `python -m src.robots.xlerobot.xlerobot_host`

## 2026-03-04 - Motor bus handshake instability
- **Context**: Jetson host start, one bus fails intermittently.
- **Error**: `Incorrect status packet` and `Could not connect on port '/dev/ttyACM1'`
- **Fix**: Added connect fallback in `xlerobot.py`:
  - Try normal handshake, then retry with `handshake=False`

## 2026-03-04 - Unsupported joints in dual-arm-only setup
- **Context**: Mac teleop sends `head_motor_*` while hardware has no head/base motors.
- **Error**: `Message fetching failed: 'head_motor_1'`
- **Fix**: Filter action keys to only configured motors in `xlerobot.py`.

## 2026-03-04 - Camera color channel mismatch on Mac feed
- **Context**: Colors appeared swapped (blue/red).
- **Cause**: Camera output mode mismatch in OpenCV path.
- **Fix**: Set camera `color_mode=ColorMode.BGR` in `config_xlerobot.py`.

## 2026-03-04 - Slow-motion follower jitter
- **Context**: Arm motion jittery when moving leaders slowly.
- **Cause**: Small command noise at high update rate.
- **Fix**: Added EMA smoothing + deadband in:
  - `examples/9_so101_bimanual_leader_wifi_teleop.py`

## 2026-03-04 - Camera warmup timeout after LeRobot update
- **Context**: Jetson host crashes at camera connect.
- **Error**: `Timed out waiting for frame ... after 1000 ms`
- **Fix**: Increased camera warmup in `config_xlerobot.py`:
  - `warmup_s=4`

## Log file locations
- Jetson host runtime log: `software/logs/xlerobot_host.log`
- Mac teleop runtime log: `software/logs/xlerobot_teleop.log`

## Template for new issues
- **Date**:
- **Machine**: Jetson / Mac
- **Command**:
- **Error**:
- **What changed before failure**:
- **Fix attempted**:
- **Status**:
