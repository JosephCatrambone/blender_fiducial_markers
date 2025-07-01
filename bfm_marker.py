import json
from dataclasses import dataclass, field

@dataclass
class MarkerPose:
    position: list[float]  # Vector 1x3
    rotation: list[float]  # Matrix 3x3 -- row-major.
    error: float

@dataclass
class MarkerDetection:
    marker_id: int = -1  # Can be thought of as the 'index' of the marker.
    corners: list[tuple[int, int]] = field(default_factory=list)  # Left, Top, Right, Bottom
    poses: list[MarkerPose] = field(default_factory=list)


