# 

import numpy
from dataclasses import dataclass

@dataclass
class FiducialMarkerDetectorConfiguration:
	marker_size_mm: float
	maximum_bit_errors: float
	downsample: int | None = None  # If nonzero, will use only one out of every 'downsample' pixels.
	contour_simplification_epsilon: float = 0.05
	threshold_window: int = 7  # How big should the nonmaximal suppression window be?
	minimum_side_length_factor: float = 0.05


class MarkerDetection:
	marker_id: int  # Can be thought of as the 'index' of the marker.
	image_corners: list[tuple[int, int]]  # Left, Top, Right, Bottom
	position: list[float]
	rotation: list[float]
	rotation_matrix: numpy.ndarray
	error: int = -1  # AKA, Hamming Distance
	marker_code: int = -1  # The original marker u64.
	detected_code: int = -1  # What was read from the image.
	

class FiducialMarkerDetector:
	"""The abstract base method for marker detectors.  Holds camera parameters like focal length and so on, plus assorted runtime configurations like real life marker size."""

	def __init__(
			self, 
			marker_size_mm: float, 
			downsample_to: tuple[int, int] | None = None, 
			dictionary: str = "ARUCO_DEFAULT",
			focal_length_x_mm: float = 1.0,
	):
		self.marker_size_mm = marker_size_mm
		self.downsample_to = downsample_to
		self.dictionary_name = dictionary
		self.dictionary = None
		self._focal_length_x_mm = focal_length_x_mm

	@property
	def focal_length_x(self):
		return self._focal_length_x_mm
	
	@property
	def fov_x(self):
		# TODO
		return 0
	
	@fov_x.setter
	def set_fov_x(self, fov_x: float):
		# TODO
		pass

	"""
	@property
	@abstractmethod
	def marker_size_mm(self):
		...
	@marker_size_mm.setter
	@abstractmethod
	def set_marker_size_mm(self, value: float):
		...
	"""

	def detect_markers(self, image: numpy.ndarray) -> list[MarkerDetection]:
		# Given an array of floats in RGBA order, find and compute the marker positions.
		raise NotImplementedError("detect_markers is being invoked directly instead of being subclassed. This is the programmer's fault.")
