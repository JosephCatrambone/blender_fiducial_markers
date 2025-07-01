# This is an OpenCV implementation of Fiducial marker tracking.
# It's faster than the Python version but requires external dependencies that can be really annoying to install.

import cv2
import numpy
import os
#from mathutils import Matrix, Vector
from .bfm_marker import MarkerDetection, MarkerPose

ARUCO_NAME_TO_DICT = {
	"ARUCO_DEFAULT": cv2.aruco.DICT_ARUCO_ORIGINAL,
	"ARUCO": cv2.aruco.DICT_ARUCO_ORIGINAL,
	"APRILTAG_36H11": cv2.aruco.DICT_APRILTAG_36H11
}

class FiducialMarkerDetectorNative:
	def __init__(self, dictionary_name: str, marker_size_mm: float, focal_length_mm: float):
		self.dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_NAME_TO_DICT[dictionary_name])
		config = cv2.aruco.DetectorParameters()
		self.detector: cv2.aruco.ArucoDetector = cv2.aruco.ArucoDetector(self.dictionary, config)
		self.focal_length_mm = focal_length_mm
		self.marker_size_mm = marker_size_mm
		self.distortion_coefficients = numpy.array([0.0, 0.0, 0.0, 0.0])

		hw = self.marker_size_mm/2.0
		self.marker_points = numpy.array([
			[-hw, hw, 0.0],
			[hw, hw, 0.0],
			[hw, -hw, 0.0],
			[-hw, -hw, 0.0],
		]).astype(numpy.float32)
	
	#@overrides
	def detect_markers(self, filepath: str) -> list[tuple[int, list[MarkerDetection]]]:
		# return super().detect_markers(image_array)
		video = cv2.VideoCapture(filepath)
		
		intrinsics = None

		frame_idx = 0
		while True:
			read_success, frame = video.read()

			if not read_success:
				print(f"Done -- read {frame_idx} frames")
				video.release()
				break

			if intrinsics is None:
				intrinsics = numpy.array([
					[self.focal_length_mm, 0.0, frame.shape[1]/2.0],
					[0.0, self.focal_length_mm, frame.shape[0]/2.0],
					[0.0, 0.0, 1.0],
				]).astype(numpy.float32)

			corners, ids, rejected = self.detector.detectMarkers(frame)
			#detected_markers = aruco_display(corners, ids, rejected, image)
			if corners is None or len(corners) == 0 or ids is None:
				# Sometimes if there are no corners detected, instead of returning an empty array, we get back None.
				print(f"Skipping frame {frame_idx} -- no detections")
				frame_idx += 1
				continue
			
			detections = []
			for c, marker_id in zip(corners, ids):
				marker = MarkerDetection()
				marker.marker_id = int(marker_id[0])
				marker.corners = [(int(p[0]), int(p[1])) for p in c[0]]  # Do we want to discard the subpixel values here?
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
				success, rotation, translation = cv2.solvePnP(self.marker_points, c, cameraMatrix=intrinsics, distCoeffs=self.distortion_coefficients, flags=cv2.SOLVEPNP_IPPE_SQUARE)
				if not success:
					print(f"Pose solve failed for frame {frame_idx}")
					frame_idx += 1
					continue

				# Convert rotation vector to a rotation matrix with the Rodrigues op: https://docs.opencv.org/4.11.0/d9/d0c/group__calib3d.html#ga61585db663d9da06b68e70cfbf6a1eac
				# OpenCV uses the compact Rodriguez representation for rotations, similar to axis-angle [theta, x, y, z], but where theta = sqrt(x^2 + y^2 + z^2) and axis = [x/theta, y/theta, z/theta]
				# See https://stackoverflow.com/questions/12933284/rodrigues-into-eulerangles-and-vice-versa
				rot, _jacobian = cv2.Rodrigues(rotation)

				# Transforms points from the _model coordinate system_ to the _camera coordinate system_.
				pose1 = MarkerPose(
					position=[float(translation[0,0]), float(translation[1,0]), float(translation[2,0])],  # Can't destructure aaaaaaaaaa
					rotation=[
						rot[0,0], rot[0,1], rot[0,2], 
						rot[1,0], rot[1,1], rot[1,2], 
						rot[2,0], rot[2,1], rot[2,2], 
					],
					error=0.0,
				)
				marker.poses = [pose1,]
				detections.append(marker)
			yield frame_idx, detections
			frame_idx += 1
