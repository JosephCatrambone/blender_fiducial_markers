# This is an OpenCV implementation of Fiducial marker tracking.
# It's faster than the Python version but requires external dependencies that can be really annoying to install.

import cv2
import numpy
#from mathutils import Matrix, Vector
from bfm import FiducialMarkerDetector, MarkerDetection

ARUCO_NAME_TO_DICT = {
	"ARUCO_DEFAULT": cv2.aruco.DICT_ARUCO_ORIGINAL,
	"ARUCO": cv2.aruco.DICT_ARUCO_ORIGINAL,
	"APRILTAG_16H11": cv2.aruco.DICT_APRILTAG_36H11
}

class FiducialMarkerDetectorNative(FiducialMarkerDetector):
	def __init__(self, *args, **kwargs):
		super(FiducialMarkerDetector, self).__init__(*args, **kwargs)
		self.dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_NAME_TO_DICT[self.dictionary_name])
		config = cv2.aruco.DetectorParameters()
		self.detector: cv2.aruco.ArucoDetector = cv2.aruco.ArucoDetector(self.dictionary, config)

		self.distortion_coefficients = kwargs.get("distortion_coefficients", None)
		self.camera_intrinsics = kwargs.get("camera_intrinsics", None)
	
	#@overrides
	def detect_markers(self, image_array: list[float], image_width: int, image_height: int) -> list[MarkerDetection]:
		# return super().detect_markers(image_array)
		channels = len(image_array)//(image_width*image_height)
		image = numpy.array(image_array)
		image = (image.reshape((image_height, image_width, channels)) * 255).astype(numpy.uint8)
		
		detections = []
		corners, ids, rejected = self.detector.detectMarkers(image)
		#detected_markers = aruco_display(corners, ids, rejected, image)

		hw = self.marker_size_mm/2.0
		marker_points = numpy.float32([
			[-hw, hw, 0.0],
			[hw, hw, 0.0],
			[hw, -hw, 0.0],
			[-hw, -hw, 0.0],
		])

		intrinsics = None
		if self.camera_intrinsics is not None:
			intrinsics = self.camera_intrinsics
		else:
			intrinsics = numpy.float32([
				[1.0, 0.0, image_width/2.0],
				[0.0, 1.0, image_height/2.0],
				[0.0, 0.0, 1.0],
			])

		for c, id in zip(corners, ids):
			marker = MarkerDetection()
			marker.marker_id = id
			marker.image_corners = [(int(p[0]), int(p[1])) for p in c[0]]  # Do we want to discard the subpixel values here?
			# This method is deprecated in 4.10+:
			#rvec, tvec, markerPoints = cv2.aruco.estimatePoseSingleMarkers(c, 0.02, self.camera_intrinsics, self.distortion_coefficients)
			# https://docs.opencv.org/4.11.0/d9/d0c/group__calib3d.html#ga549c2075fac14829ff4a58bc931c033d
			# https://github.com/npinto/opencv/blob/master/samples/python2/plane_ar.py
			"""
			SOLVEPNP_IPPE_SQUARE Special case suitable for marker pose estimation. Number of input points must be 4. Object points must be defined in the following order:
				point 0: [-squareLength / 2, squareLength / 2, 0]
				point 1: [ squareLength / 2, squareLength / 2, 0]
				point 2: [ squareLength / 2, -squareLength / 2, 0]
				point 3: [-squareLength / 2, -squareLength / 2, 0]
			"""
			success, transform, rotation = cv2.solvePnP(marker_points, c, cameraMatrix=intrinsics, distCoeffs=self.distortion_coefficients, flags=cv2.SOLVEPNP_IPPE_SQUARE)
			marker.position = [float(transform[0,0]), float(transform[0,1]), float(transform[0,2])]  # Can't destructure aaaa
			marker.rotation = [float(rotation[0,0]), float(rotation[0,1]), float(rotation[0,2])]

			if success:
				detections.append(marker)

		return detections
