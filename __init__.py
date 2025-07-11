bl_info = {
	"name": "Blender Fiducial Markers",
	"author": "Joseph Catrambone",
	"license": "AGPL",
	"version": (0, 0, 1),
	"blender": (4, 0, 0),
	"location": "Clip Editor > Tools > Track > Fiducial Markers",
	# "warning": "Requires installation of dependencies",
	"description": "Fiducial marker tracker and pose solver.",
	"category": "Tracking",
}


import bpy
import importlib
import json
import mathutils
import numpy
import os
import subprocess
import time

from .bfm_external import FiducialMarkerDetectorExternal
from .bfm_native import FiducialMarkerDetectorNative

MARKER_PREFIX = "BFM_MARKER_"

# Debug breakpoint in Blender:
#__import__('code').interact(local=dict(globals(), **locals()))

# Frustratingly, making these a collection to prevent namespace pollution changes the way we have to access them.
# As a bpy.types.Scene.bfm_config = bpy.props.CollectionProperty(type=BFM_PGT_TrackingConfiguration) we have to do settings = bpy.context.scene.bfm_config.add(); settings.whatever
# See https://docs.blender.org/api/current/bpy.props.html#collection-example
# When they're on the operator we can't seem to modify them correctly, either.
#props = self.layout.operator("bfm.track") or op = ...
# op = col.operator("bfm.track", text="Track")
# col.prop(op, "output_collection", text="Output Collection") # Doesn't show up!

# We have to register all of these individually, I guess?

# Detection/CV Side:

AR_DICTIONARIES = [
	"ARTAG",
	"ARUCO_MIP_36H12",
	"ARUCO_MIP_16H3",
	"APRILTAG_25H7",
	"APRILTAG_36H11",
	"APRILTAG_25H9",
	"CHILITAGS",
	"ARTOOLKITPLUS",
	"APRILTAG_36H10",
	"ARUCO_DEFAULT",
	"ARUCO",
	"ARTOOLKITPLUSBCH",
	"ARUCO_MIP_25H7",
	"APRILTAG_36H9",
	"APRILTAG_16H5",
]

# UI Configuration (Blender-side):

class BFM_PGT_TrackingConfiguration(bpy.types.PropertyGroup):
	# I tried adding these into the operator, which seemed like the most intuitive way to keep them, as a 'run' is generally a one-time operation.
	# I'm moving this to a collection property to add it to the scene.
	output_collection: bpy.props.PointerProperty(type=bpy.types.Collection, name="Collection", description="The collection to which empties should be added.") # type: ignore
	marker_size_mm: bpy.props.FloatProperty(name="Marker Size (mm)", description="The side-length of a marker in millimeters.")  # type: ignore
	footage_focal_length_mm: bpy.props.FloatProperty(name="Focal Length (mm)", description="The focal length (in mm) of the camera used to capture the footage.")  # type: ignore
	origin_marker: bpy.props.IntProperty(name="Origin Marker ID", default=-1, description="If >=0, specifies the origin of the 3d scene and moves the camera (and other markers) relative to this.")  # type: ignore
	generate_2d_tracks: bpy.props.BoolProperty(name="Generate 2D Tracking Markers", default=False, description="If true, generate 2D tracks in addition to the 3D empties.")  # type: ignore
	tracks_at_corners: bpy.props.BoolProperty(name="Tracks at Corners", default=False, description="If true, generates a tracking marker at each corner of a fiducial instead of one at the center.")  # type: ignore
	dictionary: bpy.props.EnumProperty(
		name="Fiducial Dictionary", 
		default="ARUCO", 
		items=[(d, d, "") for d in AR_DICTIONARIES]
	)  # type: ignore
	tracking_camera: bpy.props.PointerProperty(type=bpy.types.Camera, name="Tracking Camera", description="The camera to which relative motion will be baked if an origin marker is set OR the camera relative to which markers will be placed otherwise.")  # type: ignore
	use_opencv: bpy.props.BoolProperty(name="Use OpenCV", default=True, description="Use Python OpenCV2 to do fiducial detection instead of an external program. Increases dependencies for better quality tracking.")  # type: ignore
	
	# TODO: Also give people the option to specify MULTIPLE different static fiducial markers and average them for camera position?
	# TODO: Give user the option to parent the markers to the camera.

	@classmethod
	def register(cls):
		bpy.types.Scene.bfm_settings = bpy.props.PointerProperty(
			name="Fiducial Marker Settings",
			description="Configuration Settings for Fiducial Marker Tracking",
			type=cls,
		)
	
	@classmethod
	def unregister(cls):
		del bpy.types.Scene.bfm_settings
	
	@property
	def bake_relative_to_camera(self) -> bool:
		return self.origin_marker <= 0
	
	def validate_parameters(self) -> tuple[bool, str]:
		# Perform a sanity check of the parameters, returning 'true' on success with an empty error string.
		# On failure this method will return false and the error message.
		# For some warnings this might return 'true' and a warning message.
		if self.marker_size_mm <= 0.0:
			return False, "Marker size should be greater than zero."
		if self.footage_focal_length_mm <= 0.0:
			return False, "The footage focal length must be greater than zero."
		if self.tracking_camera is None:
			return False, "The camera for marker-relative motion needs to be set."
		return True, ""

# UI:

class BFM_PT_TrackingPanel(bpy.types.Panel):
	bl_idname = "VIEW3D_BFM_PT_TrackingPanel"
	bl_label = "Fiducial Markers"
	bl_space_type = "CLIP_EDITOR"
	bl_region_type = "TOOLS" # Not UI
	bl_category = "Track"

	def draw(self, context):
		layout = self.layout
		col = layout.column(heading="Tracking", align=True)

		col = layout.column(heading="Output", align=True)
		col.prop(context.scene.bfm_settings, "output_collection")  # Empty text because the parent section already has 'Output Collection'
		col.prop(context.scene.bfm_settings, "tracking_camera")
		col.prop(context.scene.bfm_settings, "origin_marker", text="Origin Marker ID")
		col.prop(context.scene.bfm_settings, "generate_2d_tracks", text="Generate 2D Tracks")
		col.prop(context.scene.bfm_settings, "tracks_at_corners", text="Trackers at Corners")

		col = layout.column(heading="Markers", align=True)
		col.prop(context.scene.bfm_settings, "dictionary", text="Dictionary")  # TODO: Make this an enum
		col.prop(context.scene.bfm_settings, "marker_size_mm", text="Marker Size (mm)")
		col.prop(context.scene.bfm_settings, "footage_focal_length_mm", text="Focal Length (mm)")
		col.prop(context.scene.bfm_settings, "use_opencv")
		
		_op = layout.operator("bfm.track", text="Run Tracking")
		#col = layout.column(heading="Debug", align=True)
		#col.operator("bfm.debug_reset", text="DEBUG: Reload the things!")

# Functions:

def get_clip_data(context: bpy.types.Context) -> tuple[bool, str, bpy.types.MovieClip, str]:
	"""
	Return a tuple of 'success', 'message', movie clip, and movie clip path.
	"""
	# Ensure we are in the Tracking context
	space = context.space_data
	if space.type != 'CLIP_EDITOR':
		return False, "Operator can only run in the Tracking interface!", None, ""

	# Get the current clip and frame
	clip = context.edit_movieclip
	if not clip:
		return False, "No active clip found!", None, ""
	
	# Should we fall back to checking
	# len(bpy.data.movieclips) > 0 and return bpy.data.movieclips[0]?
	
	if clip.library:
		clip_path = bpy.path.abspath(clip.filepath, library=clip.library)
	else:
		clip_path = bpy.path.abspath(clip.filepath)
	
	return True, "", clip, clip_path

def mat3_to_quaternion(mat: list[float]) -> mathutils.Quaternion:
	blender_mat = mathutils.Matrix([
		mat[0:3] + [0.0,], 
		mat[3:6] + [0.0,],
		mat[6:9] + [0.0,],
		[0.0, 0.0, 0.0, 1.0]
	])
	_tx, q, _scale = blender_mat.decompose()
	return q

def opencv_to_blender_coordinates(v: mathutils.Quaternion | mathutils.Vector):
	if isinstance(v, mathutils.Vector):
		#  OpenCV: +X right, +Y down, +Z forward.
		# Blender: +X right, -Z down, +Y forward.
		return mathutils.Vector([v.x, v.y, v.z])
	elif isinstance(v, mathutils.Quaternion):
		return mathutils.Quaternion([v.x, v.y, v.z, v.w])
	raise NotImplementedError("opencv_to_blender was passed a non-Vector, non-Quaternion.")


class BFM_OT_DebugUnregister(bpy.types.Operator):
	bl_idname = "bfm.debug_reset"
	bl_label = "Reset plugin state"
	bl_options = set()
	bl_description = "Debug tool to unregister plugin and nuke all the things."
	
	def execute(self, context):
		unregister()
		return {'FINISHED'}


class BFM_OT_Track(bpy.types.Operator):
	"""Process the current clip, generating oriented animated empties as they're encountered."""
	bl_idname = "bfm.track"
	bl_label = "Track Fiducials"  # This is what gets rendered to the button.
	bl_description = "Process the current clip, animating empties to match."
	bl_options = {'REGISTER', 'UNDO'}

	@classmethod
	def poll(cls, context):
		if context.space_data.type != "CLIP_EDITOR":
			return False
		if context.edit_movieclip is None:
			return False
		
		return True

	def execute(self, context):
		clip_loaded, clip_load_message, clip, clip_path = get_clip_data(context)
		if not clip_loaded:
			self.report({'ERROR'}, clip_load_message)
			return {'CANCELLED'}
		
		config: BFM_PGT_TrackingConfiguration = context.scene.bfm_settings
		parameters_valid, message = config.validate_parameters()
		if not parameters_valid:
			self.report({'ERROR'}, message)
			return {'CANCELLED'}
		elif message:
			self.report({'WARNING'}, message)

		# Grab the camera.
		# No need to do an indirect with `camera = bpy.data.objects.get()`, but camera = config.camera_to_bake doesn't give us translation props.
		camera = context.scene.objects[config.tracking_camera.name]

		# The user may want to specify an output collection for the empties that is different from the default one.
		output_collection = config.output_collection
		if output_collection is None:
			output_collection = context.scene.collection
		
		# Grab any existing marker IDs in the output collection.
		# We have to access the collections through bpy.data, not context.
		#for collection in bpy.data.collections:
		marker_id_to_empty = dict()
		for obj in output_collection.all_objects:
			if obj.name.startswith(MARKER_PREFIX):
				# TODO: A blender object might be renamed in a way that's incompatible. Check int parsing.
				# https://docs.blender.org/api/current/info_gotchas_internal_data_and_python_objects.html
				marker_id = int(obj.name.strip(MARKER_PREFIX))
				marker_id_to_empty[marker_id] = obj

		# TODO: when a marker goes from not-visible to visible we need to set the keyframe at the previous value OR change the interpolation type for the visible property to 'keep'.
		all_marker_ids = set()
		# Also give the user the chance to capture video tracks.
		marker_id_to_tracker = dict()

		bfm_system = None
		if config.use_opencv:
			bfm_system = FiducialMarkerDetectorNative(config.dictionary, config.marker_size_mm, config.footage_focal_length_mm)
		else:
			bfm_system = FiducialMarkerDetectorExternal(config.dictionary, config.marker_size_mm, config.footage_focal_length_mm)
		
		self.report({'INFO'}, f"Reading from movie clip at {clip_path}")
		for frame_idx, detections in bfm_system.detect_markers(clip_path):
			self.report({'INFO'}, f"Processing frame {frame_idx}... ")
			context.scene.frame_set(frame_idx)  # Not strictly necessary for setting keyframes, but updates the UI.
			visible_marker_ids = set()  # Visible in this frame.
			for marker in detections:
				# Find the marker in the collection if it exists and make a keyframe for it in the current position.
				empty = marker_id_to_empty.get(marker.marker_id, None)
				if empty is None:
					# Create a new marker and, for the previous frame, set it as not being detected.
					# We have to have a custom field on the empties so they know when they're detected and can be used to weight animations.
					bpy.ops.object.empty_add(type='ARROWS') # align='WORLD', location=(0, 0, 0), scale=(1, 1, 1))
					empty = context.object
					empty.name = MARKER_PREFIX + str(marker.marker_id)
					empty.rotation_mode = 'QUATERNION'
					marker_id_to_empty[marker.marker_id] = empty
					#output_collection.objects.link(empty)  # This seems like it happens automatically?
					self.report({'INFO'}, f"Created Empty: {empty.name}")
				
				# https://docs.blender.org/api/current/info_quickstart.html#animation
				empty.location = opencv_to_blender_coordinates(mathutils.Vector(marker.poses[0].position) / 1000.0) # Scale back to meters.
				empty.rotation_quaternion = opencv_to_blender_coordinates(mat3_to_quaternion(marker.poses[0].rotation))
				empty.bfm_detection_confidence = 1.0
				empty.empty_display_size = config.marker_size_mm / 1000.0  # Again, mm to m.

				empty.keyframe_insert(data_path="location", frame=int(frame_idx))  # index=2 would set only z, for example.
				empty.keyframe_insert(data_path="rotation_quaternion", frame=int(frame_idx))
				empty.keyframe_insert(data_path='bfm_detection_confidence', frame=frame_idx)
				empty.keyframe_insert(data_path='empty_display_size', frame=frame_idx)
				
				visible_marker_ids.add(marker.marker_id)
				all_marker_ids.add(marker.marker_id)

				# Possibly create tracking markers.
				# See https://docs.blender.org/api/current/bpy.types.MovieTrackingMarkers.html and https://docs.blender.org/api/current/bpy.types.MovieTrackingMarker.html#bpy.types.MovieTrackingMarker
				if config.generate_2d_tracks:
					if config.tracks_at_corners:
						# TODO: Add the markers at the center instead of the top-left.
						clip_width = clip.size[0]
						clip_height = clip.size[1]
					#bpy.ops.clip.add_marker_slide(CLIP_OT_add_marker={"location":(0.324317, 0.554497)}, TRANSFORM_OT_translate={"value":(0, 0, 0), "orient_type":'GLOBAL', "orient_matrix":((1, 0, 0), (0, 1, 0), (0, 0, 1)), "orient_matrix_type":'GLOBAL', "constraint_axis":(True, True, True), "mirror":False, "use_proportional_edit":False, "proportional_edit_falloff":'SMOOTH', "proportional_size":1, "use_proportional_connected":False, "use_proportional_projected":False, "snap":False, "snap_elements":{'INCREMENT'}, "use_snap_project":False, "snap_target":'CLOSEST', "use_snap_self":True, "use_snap_edit":True, "use_snap_nonedit":True, "use_snap_selectable":False, "snap_point":(0, 0, 0), "snap_align":False, "snap_normal":(0, 0, 0), "gpencil_strokes":False, "cursor_transform":False, "texture_space":False, "remove_on_cancel":False, "use_duplicated_keyframes":False, "view2d_edge_pan":False, "release_confirm":True, "use_accurate":False, "use_automerge_and_split":False})
					#bpy.ops.clip.add_marker(location=(0.324317, 0.554497))
			
			# Now that we've done all the detections, we need to go over the unseen ones.
			for mid in all_marker_ids:
				if mid not in visible_marker_ids:
					# We've seen this, but we didn't see it in the last frame, so mark as 'no detection'.
					m = marker_id_to_empty[mid]
					m.bfm_detection_confidence = 0.0
					m.keyframe_insert(data_path='bfm_detection_confidence', frame=frame_idx)
					m.empty_display_size = config.marker_size_mm / 10000.0 # mm to m / 10.  One TENTH the size in mm when not visible.
					m.keyframe_insert(data_path='empty_display_size', frame=frame_idx)
			# TODO: Go back over the first ones and insert the first frame where they're visible.

			self.report({'INFO'}, f" ... Done processeing frame {frame_idx}. Found/updated {len(detections)} markers.")
		
		# Get the camera, invert its motion, and apply that to all the other markers.
		if config.bake_relative_to_camera:
			for frame_idx in range(clip.frame_start, clip.frame_duration):
				context.scene.frame_set(frame_idx)
				for m in all_marker_ids:
					empty = marker_id_to_empty[m]
					if empty.bfm_detection_confidence == 1.0:  # There was a keyframe for this marker.
						# Rotation needs a little extra handling because we're not sure what the camera mode is:
						# While the 'rotate' method on quaternion will accept euler or quaternion, we're converting everything to quaternions to avoid footguns later.
						if camera.rotation_mode == 'QUATERNION':
							camera_rotation = camera.rotation_quaternion
						elif camera.rotation_mode == 'AXIS_ANGLE':
							camera_rotation = camera.rotation_axis_angle.to_quaternion()
						else:
							camera_rotation = camera.rotation_euler.to_quaternion()
						empty.location = camera.location + (camera_rotation @ empty.location)
						empty.rotation_quaternion.rotate(camera_rotation)
						empty.keyframe_insert(data_path="location", frame=int(frame_idx))  # index=2 would set only z, for example.
						empty.keyframe_insert(data_path="rotation_quaternion", frame=int(frame_idx))
		elif config.origin_marker >= 0:
			origin_marker = marker_id_to_empty.get(config.origin_marker)
			camera.rotation_mode = 'QUATERNION'
			
			if origin_marker is None:
				self.report({'WARNING'}, "Origin marker was set but the fiducial could not be located in the scene. Not baking.")
			else:
				self.report({'INFO'}, "Applying origin marker root motion.")
				for frame_idx in range(clip.frame_start, clip.frame_duration):
					context.scene.frame_set(frame_idx)
					# A note on applying the transform:
					# When the origin marker isn't visible to us, we still use the interpolated position to invert OTHER KEYFRAMED MARKERS.
					# We do NOT insert keyframes for the camera, however.
					inverse_rotation = origin_marker.rotation_quaternion.inverted()
					inverse_translation = origin_marker.location * -1.0
					# Apply the inverse transform to all markers currently keyframed.
					for m in all_marker_ids:
						if m == config.origin_marker:
							continue
						to_transform = marker_id_to_empty[m]
						if to_transform.bfm_detection_confidence == 1.0:
							to_transform.rotation_quaternion.rotate(inverse_rotation)
							to_transform.keyframe_insert(data_path="rotation_quaternion", frame=int(frame_idx))
							to_transform.location += inverse_translation
							to_transform.keyframe_insert(data_path="location", frame=int(frame_idx))  # index=2 would set only z, for example.
					# Also apply to the camera if the marker is visible.
					if camera and origin_marker.bfm_detection_confidence == 1.0:
						camera.rotation_quaternion.rotate(inverse_rotation)
						camera.keyframe_insert(data_path="rotation_quaternion", frame=frame_idx)
						camera.location = inverse_translation
						camera.keyframe_insert(data_path="location", frame=frame_idx)

		self.report({'INFO'}, "Finished reading fiducials.")
		return {'FINISHED'}

# Blender Addon Registration and Boilerplate:

classes = [
	BFM_PGT_TrackingConfiguration,
	BFM_PT_TrackingPanel,
	BFM_OT_DebugUnregister,
	BFM_OT_Track,
]

def register():
	print("Registering!")
	#BFM_PGT_TrackingConfiguration.register() # Register class calls the interal classmethod?
	for c in classes: 
		bpy.utils.register_class(c)
	# Also register a custom type for objects.  
	# TODO: Can we do this only for empties or does the custom property need to apply to all objects?
	bpy.types.Object.bfm_detection_confidence = bpy.props.FloatProperty(name="BFM Detection Confidence")
	print("Done")


def unregister():
	print("Unregistering")
	del bpy.types.Object.bfm_detection_confidence
	for c in reversed(classes):
		bpy.utils.unregister_class(c)
	print("Done")

def main():
	try:
		unregister()
	except Exception:
		print("Tracking panel class not found!  We're good.")
	register()

if __name__ == "__main__":
	main()

"""
import sys
import os
import bpy

blend_dir = "/home/joseph/PythonProjects/"
if blend_dir not in sys.path:
   sys.path.append(blend_dir)

import importlib
bfm = importlib.import_module("blender_fiducial_markers")
importlib.reload(bfm)
bfm.main()
"""