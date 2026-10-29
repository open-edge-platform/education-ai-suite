import json
import logging
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

from components.va.roi_filter import default_label, filter_objects

logger = logging.getLogger(__name__)


STANDING_LABEL_FILTER = "stand,stand_raise_up"


class PoseStatsTracker:
    """Incrementally parses a front_posture.txt-style JSON-lines file into
    engagement statistics (student_count, stand_count, raise_up_count, per-
    student stand/raise history). One instance per pipeline/session; call
    get_pose_stats() repeatedly, passing back the state it returns each time.
    """

    def __init__(
        self,
        min_frames_for_transition: int = 3,
        min_frames_for_transition_unid: int = 15,
        absence_threshold: int = 90,
        min_stand_frames: int = 10,
        center_dist_threshold: float = 0.1,
        unidentified_max: int = 50,
        stale_unidentified_threshold: int = 30,
        student_count_window_frames: int = 150,
    ):
        self.min_frames_for_transition = min_frames_for_transition
        self.min_frames_for_transition_unid = min_frames_for_transition_unid
        self.absence_threshold = absence_threshold
        self.min_stand_frames = min_stand_frames
        self.center_dist_threshold = center_dist_threshold
        self.unidentified_max = unidentified_max
        self.stale_unidentified_threshold = stale_unidentified_threshold
        self.student_count_window_frames = student_count_window_frames

    def get_pose_stats(
        self, front_posture_file: str, previous_state: Optional[Dict] = None
    ) -> tuple[Dict, Dict]:
        """Incrementally analyze front_posture.txt and generate pose statistics.
        Only processes new lines since last call, reusing previous results.

        Returns (statistics_dict, new_state_dict) -- pass new_state_dict back
        in as previous_state on the next call.
        """
        posture_file = Path(front_posture_file)

        if previous_state is None:
            previous_state = {
                "processed_lines": 0,
                "total_frames": 0,
                "occupancy_window": deque(maxlen=self.student_count_window_frames),
                "student_states": {},
                "student_stand_counts": {},
                "student_raise_counts": {},
                "unidentified_objects": [],
                "total_raise_count_no_id": 0,
            }

        if not posture_file.exists():
            return {
                "student_count": 0,
                "stand_count": 0,
                "raise_up_count": 0,
                "stand_reid": [],
            }, previous_state

        try:
            with open(posture_file, "r") as f:
                all_lines = f.readlines()

            processed_lines = previous_state["processed_lines"]
            new_lines = all_lines[processed_lines:]

            if not new_lines:
                return self._calculate_stats(previous_state), previous_state

            frame_base = previous_state["total_frames"]
            new_frames = 0

            for line in new_lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    frame = json.loads(line)
                except json.JSONDecodeError:
                    continue

                frame_idx = frame_base + new_frames
                new_frames += 1

                objects = frame.get("objects", [])
                # Defensive: a 0-sized bbox can't be a real detection. Nothing
                # in the new pipeline design actually zeroes bboxes anymore
                # (see roi_filter.py), so this should be a no-op in practice.
                valid_objects = [
                    obj for obj in objects
                    if obj.get("detection", {}).get("bounding_box", {}).get("x_max", 0) > 0
                ]
                standing_objects = filter_objects(
                    valid_objects,
                    label=STANDING_LABEL_FILTER,
                )

                previous_state["occupancy_window"].append(len(valid_objects))

                self._process_frame(frame_idx, standing_objects, valid_objects, previous_state)

            previous_state["processed_lines"] = len(all_lines)
            previous_state["total_frames"] = frame_base + new_frames

            return self._calculate_stats(previous_state), previous_state

        except Exception as e:
            logger.error(f"Error in incremental pose statistics: {e}")
            return {
                "student_count": 0,
                "stand_count": 0,
                "raise_up_count": 0,
                "stand_reid": [],
            }, previous_state

    def _process_frame(self, frame_idx: int, standing_objects: List, all_objects: List, state: Dict):
        """Process a single frame, updating tracking state in-place.
        """
        MIN_FRAMES_FOR_TRANSITION = self.min_frames_for_transition
        MIN_FRAMES_FOR_TRANSITION_UNID = self.min_frames_for_transition_unid
        ABSENCE_THRESHOLD = self.absence_threshold
        MIN_STAND_FRAMES = self.min_stand_frames
        CENTER_DIST_THRESHOLD = self.center_dist_threshold
        UNIDENTIFIED_MAX = self.unidentified_max

        student_states = state["student_states"]
        student_stand_counts = state["student_stand_counts"]
        student_raise_counts = state["student_raise_counts"]
        unidentified_objects = state["unidentified_objects"]

        standing_ids = {obj.get("id", 0) for obj in standing_objects if obj.get("id", 0) > 0}

        seen_student_ids = set()
        matched_unidentified = set()

        for obj in all_objects:
            detection = obj.get("detection", {})
            label = default_label(obj)
            student_id = obj.get("id", 0)
            bbox = detection.get("bounding_box", {})

            is_raising = label in ["sit_raise_up", "stand_raise_up"]
            is_standing_now = student_id in standing_ids

            if student_id > 0:
                seen_student_ids.add(student_id)

                if student_id not in student_states:
                    if student_id not in student_raise_counts:
                        student_raise_counts[student_id] = 0
                    if is_raising:
                        student_raise_counts[student_id] += 1
                    student_states[student_id] = {
                        "last_seen_frame": frame_idx,
                        "is_raising": is_raising,
                        "raise_buffer": 0,
                        "continuous_frames": 1 if is_standing_now else 0,
                        "stand_confirmed": False,
                    }
                else:
                    st = student_states[student_id]
                    st["last_seen_frame"] = frame_idx

                    if is_standing_now:
                        st["continuous_frames"] += 1
                        if not st["stand_confirmed"] and st["continuous_frames"] >= MIN_STAND_FRAMES:
                            student_stand_counts[student_id] = student_stand_counts.get(student_id, 0) + 1
                            st["stand_confirmed"] = True
                    else:
                        # Not in the standing set this frame -- sitting back
                        # down resets the streak; standing up again later
                        # needs MIN_STAND_FRAMES afresh, same as re-appearing
                        # after an absence.
                        st["continuous_frames"] = 0
                        st["stand_confirmed"] = False

                    if is_raising != st["is_raising"]:
                        st["raise_buffer"] += 1
                        if st["raise_buffer"] >= MIN_FRAMES_FOR_TRANSITION:
                            if is_raising:
                                student_raise_counts[student_id] += 1
                            st["is_raising"] = is_raising
                            st["raise_buffer"] = 0
                    else:
                        st["raise_buffer"] = 0

            else:
                cx = (bbox.get("x_min", 0) + bbox.get("x_max", 0)) / 2
                cy = (bbox.get("y_min", 0) + bbox.get("y_max", 0)) / 2

                best_match_idx = -1
                best_dist = CENTER_DIST_THRESHOLD

                for idx, unid_obj in enumerate(unidentified_objects):
                    if idx in matched_unidentified:
                        continue
                    ux, uy = unid_obj["center"]
                    dist = ((cx - ux) ** 2 + (cy - uy) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_match_idx = idx

                if best_match_idx >= 0:
                    unid_obj = unidentified_objects[best_match_idx]
                    matched_unidentified.add(best_match_idx)
                    unid_obj["center"] = (cx, cy)

                    if is_raising != unid_obj["is_raising"]:
                        unid_obj["raise_buffer"] += 1
                        if unid_obj["raise_buffer"] >= MIN_FRAMES_FOR_TRANSITION_UNID:
                            if is_raising:
                                unid_obj["raise_count"] += 1
                                state["total_raise_count_no_id"] += 1
                            unid_obj["is_raising"] = is_raising
                            unid_obj["raise_buffer"] = 0
                    else:
                        unid_obj["raise_buffer"] = 0

                    unid_obj["last_seen_frame"] = frame_idx
                elif len(unidentified_objects) < UNIDENTIFIED_MAX:
                    unidentified_objects.append({
                        "center": (cx, cy),
                        "is_raising": is_raising,
                        "raise_buffer": 0,
                        "raise_count": 0,
                        "last_seen_frame": frame_idx,
                    })

        state["unidentified_objects"] = [
            obj for obj in unidentified_objects
            if frame_idx - obj["last_seen_frame"] < self.stale_unidentified_threshold
        ]

        for student_id in list(student_states.keys()):
            if student_id not in seen_student_ids:
                if frame_idx - student_states[student_id]["last_seen_frame"] >= ABSENCE_THRESHOLD:
                    del student_states[student_id]

    def _calculate_stats(self, state: Dict) -> Dict:
        """Calculate current statistics from accumulated state."""
        if state["total_frames"] == 0:
            return {
                "student_count": 0,
                "stand_count": 0,
                "raise_up_count": 0,
                "stand_reid": [],
                "raise_reid": [],
            }

        occupancy_window = state["occupancy_window"]
        student_count = round(sum(occupancy_window) / len(occupancy_window)) if occupancy_window else 0

        stand_count = sum(state["student_stand_counts"].values())
        raise_up_count = (
            sum(state["student_raise_counts"].values()) + state["total_raise_count_no_id"]
        )
        stand_reid = [
            {"student_id": sid, "count": cnt}
            for sid, cnt in sorted(state["student_stand_counts"].items())
            if cnt > 0
        ]
        raise_reid = [
            {"student_id": sid, "count": cnt}
            for sid, cnt in sorted(
                state["student_raise_counts"].items(), key=lambda x: x[1], reverse=True
            )
            if cnt > 0
        ]

        return {
            "student_count": student_count,
            "stand_count": stand_count,
            "raise_up_count": raise_up_count,
            "stand_reid": stand_reid,
            "raise_reid": raise_reid,
        }
