import json
from dataclasses import dataclass, field

@dataclass
class MarkerPose:
    position: list[float]
    rotation: list[float]  # Matrix 3x3
    error: float

@dataclass
class MarkerDetection:
    frame_idx: int = -1
    marker_id: int = -1  # Can be thought of as the 'index' of the marker.
    corners: list[tuple[int, int]] = field(default_factory=list)  # Left, Top, Right, Bottom
    poses: list[MarkerPose] = field(default_factory=list)

    @classmethod
    def from_json_string(cls, line: str) -> tuple[int, list]:
        data = json.loads(line)
        frame_idx = data.pop("frame_id")
        detections = data.pop("detections")
        markers = list()
        for d in detections:
            marker_id = d["marker_id"]
            corners = [(int(x), int(y)) for x,y in zip(d["corners"][0::2], d["corners"][1::2], )]
            poses = list()
            for p in d["poses"]:
                poses.append(
                    MarkerPose(
                        position=p["translation"],
                        rotation=p["rotation"],
                        error=p["error"]
                    )
                )
            markers.append(cls(frame_idx=frame_idx, marker_id=marker_id, corners=corners, poses=poses))
        return frame_idx, markers

