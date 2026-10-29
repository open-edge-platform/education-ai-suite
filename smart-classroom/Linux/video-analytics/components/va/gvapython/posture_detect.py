"""
Reads the YOLO-pose keypoint tensor DL Streamer's gvadetect attaches natively
(format "body-pose/coco-17", 17 keypoints x (x, y), ROI-relative fractions)
and applies the geometric heuristic:
  - hip->knee angle vs. vertical < 30deg => "stand", else "sit"
  - per-leg fallback when only one leg's keypoints are confident (> 0.5)
  - wrist above shoulder (smaller y) on either side => "_raise_up" suffix
  - keypoints falling outside the ROI bounds (20% tolerance) get their
    confidence discounted by 0.9 instead of being dropped outright
"""

import math

from gstgva.tensor import Tensor
from gstgva.util import libgst

KEYPOINT_FORMAT = "body-pose/coco-17"

NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR = 0, 1, 2, 3, 4
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_ELBOW, RIGHT_ELBOW = 7, 8
LEFT_WRIST, RIGHT_WRIST = 9, 10
LEFT_HIP, RIGHT_HIP = 11, 12
LEFT_KNEE, RIGHT_KNEE = 13, 14
LEFT_ANKLE, RIGHT_ANKLE = 15, 16

CONF_THRESHOLD = 0.5
STAND_ANGLE_DEG = 30.0
OOB_TOLERANCE = 0.2
OOB_CONFIDENCE_PENALTY = 0.1

def _angle_from_vertical(vx, vy):
    norm = math.sqrt(vx * vx + vy * vy)
    if norm == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, vy / norm))
    return math.degrees(math.acos(cos_angle))


def _make_tensor(name, fields):
    structure = libgst.gst_structure_new_empty(name.encode("utf-8"))
    tensor = Tensor(structure)
    for key, value in fields.items():
        tensor[key] = value
    return tensor


def detect_posture(keypoints):
    """keypoints: list of 17 (x, y, confidence) tuples, x/y as ROI fractions."""
    posture = "sit"
    raise_up = False

    lh, rh = keypoints[LEFT_HIP], keypoints[RIGHT_HIP]
    lk, rk = keypoints[LEFT_KNEE], keypoints[RIGHT_KNEE]
    ls, rs = keypoints[LEFT_SHOULDER], keypoints[RIGHT_SHOULDER]
    lw, rw = keypoints[LEFT_WRIST], keypoints[RIGHT_WRIST]

    if lh[2] > CONF_THRESHOLD and rh[2] > CONF_THRESHOLD and lk[2] > CONF_THRESHOLD and rk[2] > CONF_THRESHOLD:
        left_angle = _angle_from_vertical(lk[0] - lh[0], lk[1] - lh[1])
        right_angle = _angle_from_vertical(rk[0] - rh[0], rk[1] - rh[1])
        if left_angle < STAND_ANGLE_DEG and right_angle < STAND_ANGLE_DEG:
            posture = "stand"
    elif lh[2] > CONF_THRESHOLD and lk[2] > CONF_THRESHOLD:
        if _angle_from_vertical(lk[0] - lh[0], lk[1] - lh[1]) < STAND_ANGLE_DEG:
            posture = "stand"
    elif rh[2] > CONF_THRESHOLD and rk[2] > CONF_THRESHOLD:
        if _angle_from_vertical(rk[0] - rh[0], rk[1] - rh[1]) < STAND_ANGLE_DEG:
            posture = "stand"
    elif lh[2] > CONF_THRESHOLD and rh[2] > CONF_THRESHOLD:
        posture = "sit"

    if lw[2] > CONF_THRESHOLD and ls[2] > CONF_THRESHOLD and lw[1] < ls[1]:
        raise_up = True
    if rw[2] > CONF_THRESHOLD and rs[2] > CONF_THRESHOLD and rw[1] < rs[1]:
        raise_up = True

    if raise_up:
        posture += "_raise_up"
    return posture


class PostureDetect:
    def process_frame(self, frame):
        sit_count = stand_count = raise_count = 0

        for roi in frame.regions():
            kp_tensor = None
            for tensor in roi.tensors():
                if tensor.format() == KEYPOINT_FORMAT:
                    kp_tensor = tensor
                    break

            if kp_tensor is None:
                continue

            raw = list(kp_tensor.data())
            confidences = list(kp_tensor.confidence())
            keypoints = []
            for i in range(17):
                x, y = raw[2 * i], raw[2 * i + 1]
                conf = confidences[i] if i < len(confidences) else 1.0
                if x < -OOB_TOLERANCE or x > 1.0 + OOB_TOLERANCE or y < -OOB_TOLERANCE or y > 1.0 + OOB_TOLERANCE:
                    conf *= OOB_CONFIDENCE_PENALTY
                keypoints.append((x, y, conf))

            posture = detect_posture(keypoints)

            posture_tensor = _make_tensor("posture", {
                "type": "posture_result",
                "confidence": roi.confidence(),
            })
            posture_tensor.set_label(posture)
            roi.add_tensor(posture_tensor)

            if posture.startswith("stand"):
                stand_count += 1
            else:
                sit_count += 1
            if posture.endswith("raise_up"):
                raise_count += 1

        count_region = frame.add_region(0, 0, 0, 0, "", 0.0)
        count_tensor = _make_tensor(
            "count_text",
            {"label": f"Sit: {sit_count} | Stand: {stand_count} | Raise Up: {raise_count}"},
        )
        count_region.add_tensor(count_tensor)
        return True
