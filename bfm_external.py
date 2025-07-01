import os
import subprocess

from bfm_marker import MarkerDetection, MarkerPose

EXECUTABLE_NAME = "fiducial_track_video"

class FiducialMarkerDetectorNative:
	def __init__(self, dictionary_name: str, marker_size_mm: float, focal_length_mm: float):
		self.dictionary_name = dictionary_name
		self.marker_size_mm = marker_size_mm
		self.focal_length_mm = focal_length_mm
		
	def detect_markers(self, filepath: str) -> list[tuple[int, list[MarkerDetection]]]:
		executable_path = os.path.join(os.path.dirname(__file__), EXECUTABLE_NAME)
		args=[executable_path, filepath, self.dictionary_name, str(self.marker_size_mm)]

		# On Windows we need to set process flags to ensure that we run async.  Also, if shell=True then we need to pass a string of args rather than a list.
		# Also, if shell=True then we need to do " ".join(args)
		proc = subprocess.Popen(
			args=args,
			stdin=None,
			stdout=subprocess.PIPE,
			text=True,
			shell=False,
		)

		try:
			for line in proc.stdout:
				print(line)
				yield MarkerDetection.from_json_string(line)
		finally:
			proc.wait()