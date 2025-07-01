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
    output_collection: bpy.props.PointerProperty(type=bpy.types.Collection, name="Collection") # type: ignore
    marker_size_mm: bpy.props.FloatProperty(name="Marker Size (mm)", description="The side-length of a marker in millimeters.")  # type: ignore
    origin_marker: bpy.props.IntProperty(name="Origin Marker ID", default=0)  # type: ignore
    generate_2d_tracks: bpy.props.BoolProperty(name="Generate 2D Tracking Markers", default=False, description="Generate 2D tracks in addition to the 3D empties.")  # type: ignore
    empties_at_center: bpy.props.BoolProperty(name="Empties at Center", default=True, description="If true, generates empties at the center of the detected markers, else generates them at the top-left corner.")  # type: ignore
    dictionary: bpy.props.EnumProperty(
        name="Fiducial Dictionary", 
        default="ARUCO", 
        items=[(d, d, "") for d in AR_DICTIONARIES]
    )  # type: ignore

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
        #run = layout.operator("bfm.track", text="Run Tracking")

        col = layout.column(heading="Output", align=True)
        col.prop(context.scene.bfm_settings, "output_collection")  # Empty text because the parent section already has 'Output Collection'

        col = layout.column(heading="Space Configuration", align=True)
        col.prop(context.scene.bfm_settings, "marker_size_mm", text="Marker Size (mm)")
        col.prop(context.scene.bfm_settings, "origin_marker", text="Origin Marker ID")

        col = layout.column(heading="Markers", align=True)
        col.prop(context.scene.bfm_settings, "dictionary", text="Dictionary")  # TODO: Make this an enum
        col.prop(context.scene.bfm_settings, "generate_2d_tracks", text="Generate 2D Tracks")
        col.prop(context.scene.bfm_settings, "empties_at_center", text="Empties at Center")

        _op = layout.operator("bfm.track", text="Run Tracking")

        col = layout.column(heading="Debug", align=True)
        col.operator("bfm.debug_reset", text="DEBUG: Reload the things!")

# Functions:

def get_active_movie_clip(context: bpy.types.Context):
    """
    If the current context is a CLIP_EDITOR, pull the movie clip from that.
    If neither is true and there's only one MOVIE_CLIP loaded, return that.
    Else return None.
    """
    # When invoked from our tool space in the main function this will be a CLIP_EDITOR, but we want to reuse elsewhere.
    # We can only use context.edit_movieclip is our curent context.space_data is CLIP_EDITOR
    if context.space_data.type == 'CLIP_EDITOR':
        clip = context.edit_movieclip
        if not clip:
            return None
        return clip
    elif len(bpy.data.movieclips) == 1:
        return bpy.data.movieclips[0]
    return None

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
        # Ensure we are in the Tracking context
        space = context.space_data
        if space.type != 'CLIP_EDITOR':
            self.report({'ERROR'}, "Operator can only run in the Tracking interface!")
            return {'CANCELLED'}

        # Get the current clip and frame
        clip = context.edit_movieclip
        if not clip:
            self.report({'ERROR'}, "No active clip found!")
            return {'CANCELLED'}
        
        if clip.library:
            clip_path = bpy.path.abspath(clip.filepath, library=clip.library)
        else:
            clip_path = bpy.path.abspath(clip.filepath)
        
        config: BFM_PGT_TrackingConfiguration = context.scene.bfm_settings

        if config.marker_size_mm <= 0.0:
            self.report({'ERROR'}, "Marker size should be greater than zero.")
            return {'CANCELLED'}

        #self.report(
        #    {'INFO'}, "F: {:.2f}  B: {:s}  S: {!r}".format(
        #        self.my_float, self.my_bool, self.my_string,
        #    )
        #)

        # Select a camera or get the default one.

        #bpy.data.movieclips['Something.mov'].name
        #bpy.data.scenes['Scene'].frame_current
        #bpy.data.scenes['Scene'].frame_start
        #bpy.data.scenes['Scene'].frame_end
        #bpy.data.movieclips['P1000213.MOV'].frame_start
        #bpy.data.movieclips['P1000213.MOV'].frame_duration
        #current_frame = clip.frame_current
        #current_frame = bpy.data.scenes['Scene'].frame_current
        #current_frame = context.scene.frame_current

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

        bfm_system = FiducialMarkerDetectorNative(config.dictionary, config.marker_size_mm, 1.0)
        
        total_time = 0.0
        self.report({'INFO'}, f"Reading from movie clip at {clip_path}")
        for frame_idx, detections in bfm_system.detect_markers(clip_path):
            self.report({'INFO'}, f"Processing frame {frame_idx}... ")
            start_time = time.time()
            print(f"Found {len(detections)} in frame {frame_idx}")
            for marker in detections:
                print(f"Marker {marker.marker_id} at {marker.poses[0].position}")
                # Find the marker in the collection if it exists and make a keyframe for it in the current position.
                empty = marker_id_to_empty.get(marker.marker_id, None)
                if empty is None:
                    # Create a new marker and, for the previous frame, set it as not being detected.
                    # We have to have a custom field on the empties so they know when they're detected and can be used to weight animations.
                    bpy.ops.object.empty_add(type='ARROWS') # align='WORLD', location=(0, 0, 0), scale=(1, 1, 1))
                    empty = context.object
                    empty.name = MARKER_PREFIX + str(marker.marker_id)
                    marker_id_to_empty[marker.marker_id] = empty
                    #output_collection.objects.link(empty)  # This seems like it happens automatically?
                    self.report({'INFO'}, f"Created Empty: {empty.name}")
                
                # https://docs.blender.org/api/current/info_quickstart.html#animation
                # There's also a hilariously hacky way to add absolute position:
                #bpy.ops.object.location_clear(clear_delta=False)
                #bpy.ops.object.rotation_clear(clear_delta=False)
                #bpy.ops.transform.translate(value=(0.344667, 2.27031, 1.20884), orient_type='GLOBAL', orient_matrix=((1, 0, 0), (0, 1, 0), (0, 0, 1)), orient_matrix_type='GLOBAL', mirror=False, use_proportional_edit=False, proportional_edit_falloff='SMOOTH', proportional_size=1, use_proportional_connected=False, use_proportional_projected=False, snap=False, snap_elements={'INCREMENT'}, use_snap_project=False, snap_target='CLOSEST', use_snap_self=True, use_snap_edit=True, use_snap_nonedit=True, use_snap_selectable=False)
                empty.location = marker.poses[0].position
                empty.keyframe_insert(data_path="location", frame=float(frame_idx))  # index=2 would set only z, for example.
                empty.rotation_quaternion = mat3_to_quaternion(marker.poses[0].rotation)
                empty.keyframe_insert(data_path="rotation_quaternion", frame=float(frame_idx))
                if config.origin_marker > 0 and marker.marker_id == config.origin_marker:
                    pass
            end_time = time.time()
            delta_time = end_time - start_time
            total_time += delta_time
            self.report({'INFO'}, f" ... Done processeing frame {frame_idx} in {delta_time} seconds. Found/updated {len(detections)} markers.")
            # TODO: Reverse the camera one.

        self.report({'INFO'}, "Finished reading fiducials.")
        return {'FINISHED'}

# Helpers:

def mat3_to_quaternion(mat: list[float]) -> mathutils.Quaternion:
    blender_mat = mathutils.Matrix([
        mat[0:3] + [0.0,], 
        mat[3:6] + [0.0,],
        mat[6:9] + [0.0,],
        [0.0, 0.0, 0.0, 1.0]
    ])
    _tx, q, _scale = blender_mat.decompose()
    return q


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
    print("Done")


def unregister():
    print("Unregistering")
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