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
import mathutils
import numpy
import subprocess
import time

#from .bfm import FiducialMarkerDetector
from .bfm_native import FiducialMarkerDetectorNative as Detector
try:
    from .bfm_native import FiducialMarkerDetectorNative as Detector
except ImportError as e:
    print(f"Could not import native fiducial marker library - probably missing OpenCV - falling back to pure Python.  Exception: {e}")
    from .bfm_python import FiducialMarkerDetectorPython as Detector

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

class BFM_PGT_TrackingConfiguration(bpy.types.PropertyGroup):
    # I tried adding these into the operator, which seemed like the most intuitive way to keep them, as a 'run' is generally a one-time operation.
    # I'm moving this to a collection property to add it to the scene.
    output_collection: bpy.props.PointerProperty(type=bpy.types.Collection, name="Collection") # type: ignore
    marker_size_mm: bpy.props.FloatProperty(name="Marker Size (mm)", description="The side-length of a marker in millimeters.")  # type: ignore
    origin_marker: bpy.props.IntProperty(name="Origin Marker ID", default=0)  # type: ignore
    generate_2d_tracks: bpy.props.BoolProperty(name="Generate 2D Tracking Markers", default=False, description="Generate 2D tracks in addition to the 3D empties.")  # type: ignore
    empties_at_center: bpy.props.BoolProperty(name="Empties at Center", default=True, description="If true, generates empties at the center of the detected markers, else generates them at the top-left corner.")  # type: ignore
    dictionary: bpy.props.StringProperty(name="Fiducial Dictionary", default="ARUCO_DEFAULT")  # type: ignore

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

def get_viewer_area_and_space(context: bpy.types.Context, area_of_type: str, space_of_type: str):
    # Returns area and space matching the 'of_type', like 'IMAGE_EDITOR'
    for viewer_area in context.screen.areas:
        if viewer_area.type == area_of_type:
            for space in viewer_area.spaces:
                if space.type == space_of_type:
                    return viewer_area, space
    return None, None

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

def iterate_video_frames_blender(
        context: bpy.types.Context,
        data: bpy.types.BlendData,
        movie_clip: bpy.types.MovieClip | str | None = None, 
        start_frame: int | None = None, 
        end_frame: int | None = None,
    ):
    """
    Returns an iterator that yields arrays of pixel data for each frame of the specified movie clip.
    This will temporarily transform one of the viewing areas into an IMAGE_EDITOR type between yields.
    @param movie_clip is either the movie clip to load or the name of the clip. If 'None', will use the one from the current scene context.
    @param start_frame is the point that generation should begin. If None, will use the timeline first frame.
    @param end_frame is the last frame (exclusive) that should be yielded.  If None, will use the timeline.
    """
    # Populate all fields 'smartly'.
    if start_frame is None:
        start_frame = context.scene.frame_start
    start_frame = int(start_frame)  # type: ignore
    if end_frame is None:
        end_frame = context.scene.frame_end
    end_frame = int(end_frame)  # type: ignore

    if movie_clip is None:
        # First, try to pull from the tracking context.
        movie_clip = get_active_movie_clip(context)
    elif isinstance(movie_clip, str):
        # See if we can get a movie clip from the loaded data.
        movie_clip = data.movieclips(movie_clip)
    if movie_clip is None:
        raise Exception("The active movie clip could not be determined or loaded. It is possible the context is missing or the name is incorrect.")

    # TODO: We need to make a temporary area on this screen with an image editor.
    # bpy.data.screens[current] points to context.screen.areas
    
    # This is taken from and modified from a stackoverflow post by Kivig.
    original_area_type = None
    original_space_type = None
    viewer_area = None
    viewer_space = None
    for candidate_area in context.screen.areas:
        if candidate_area.type == 'IMAGE_EDITOR':
            viewer_area = candidate_area
            break
    if viewer_area is None:
        original_area_type = context.screen.areas[0].type
        context.screen.areas[0].type = 'IMAGE_EDITOR'
        viewer_area = context.screen.areas[0]
        original_space_type = viewer_area.spaces[0].type
        # viewer_area.spaces[0].type = 'IMAGE_EDITOR'  # This is read-only?  Is the type implicit on making it an image editor?
        viewer_space = viewer_area.spaces[0]
    else:
        for candidate_space in viewer_area.spaces:
            if candidate_space.type == 'IMAGE_EDITOR':
                viewer_space = candidate_space
                break
    if viewer_space is None:
        original_space_type = viewer_area.spaces[0].type
        viewer_space = viewer_area.spaces[0]
        viewer_space.type = 'IMAGE_EDITOR'
        
    
    # Load image sequence or movie clip.
    # Can't do the easy thing and just assign + read.
    # >>> context.screen.areas[2].spaces[0].image = bpy.data.movieclips['P1000213.MOV']
    # Traceback (most recent call last):
    #  File "<blender_console>", line 1, in <module>
    # TypeError: bpy_struct: item.attr = val: SpaceImageEditor.image expected a Image type, not MovieClip
    #>>> context.screen.areas[2].spaces[0].image.pixels[0]
    image = data.images.load(movie_clip.filepath)
    image_width = image.size[0]
    image_height = image.size[1]
    viewer_space.image = image
    previous_frame = None

    for frame_idx in range(start_frame, end_frame):
        viewer_space.image_user.frame_offset = frame_idx  # This works for older versions.
        #context.scene.frame_current = frame_idx
        
        # Force refresh
        viewer_space.display_channels = 'COLOR_ALPHA'
        viewer_space.display_channels = 'COLOR'

        image_data = numpy.array(viewer_space.image.pixels).reshape((image_height, image_width, len(viewer_space.image.pixels)//(image_height*image_width)))
        image_data = image_data[::-1,:,:] # Because we can't have nice things, the image is also flipped.
        if previous_frame is not None and numpy.allclose(image_data, previous_frame, rtol=1e-8, atol=1e-8):
            print("Skipping duplicate frame.")
            continue
        yield(image_data)

        #pixels = list(viewer_space.image.pixels)
        #tmp = bpy.data.images.new(name="sample"+str(frame), width=w, height=h, alpha=False, float_buffer=False)
        #tmp.pixels = pixels
        
        previous_frame = image_data
    image.user_clear()
    data.images.remove(image)

    # Restore the starting state.
    if original_space_type is not None:
        try:
            viewer_space.type = original_space_type
        except Exception:
            pass
    if original_area_type is not None:
        try:
            viewer_area.type = original_area_type
        except Exception:
            pass

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
        
        config: BFM_PGT_TrackingConfiguration = context.scene.bfm_settings

        if config.marker_size_mm <= 0.0:
            self.report({'ERROR'}, "Marker size should be greater than zero.")
            return {'CANCELLED'}

        #self.report(
        #    {'INFO'}, "F: {:.2f}  B: {:s}  S: {!r}".format(
        #        self.my_float, self.my_bool, self.my_string,
        #    )
        #)

        #bpy.data.movieclips['Something.mov'].name
        #bpy.data.scenes['Scene'].frame_current
        #bpy.data.scenes['Scene'].frame_start
        #bpy.data.scenes['Scene'].frame_end
        #bpy.data.movieclips['P1000213.MOV'].frame_start
        #bpy.data.movieclips['P1000213.MOV'].frame_duration
        #current_frame = clip.frame_current
        #current_frame = bpy.data.scenes['Scene'].frame_current
        #current_frame = context.scene.frame_current

        
        fm = Detector(
            marker_size_mm=config.marker_size_mm, 
            downsample_to=(1920, 1080), 
            dictionary=config.dictionary, 
            focal_length_x_mm=1.0,
        )

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

        total_time = 0.0
        for frame_idx, pixels in enumerate(iterate_video_frames_blender(context, bpy.data, clip)):
            self.report({'INFO'}, f"Processing frame {frame_idx}... ")
            start_time = time.time()
            numpy.save(f"/home/joseph/tmp/debug_frame_{frame_idx}", pixels)
            markers = fm.detect_markers(pixels)
            print(f"Found {len(markers)} in frame {frame_idx}")
            for marker in markers:
                print(f"Marker {marker.marker_id} at {marker.position}")
                # Some fiddling needed to go between the numpy vector types and the Blender types.
                # See https://docs.blender.org/api/current/mathutils.html
                
                # As a reminder, the marker describes how to go from the model coordinate system to camera coordinate system.
                
                # This is a bit of a hack to get our rotation matrix into a quaternion.
                translation = numpy.array(marker.position).reshape((3, 1))
                rotation = marker.rotation_matrix
                skew = numpy.array([0, 0, 0, 1])
                # >>> tx = numpy.array([1, 2, 3]).reshape((3,1))
                # >>> rx = numpy.eye(3)
                # >>> skew = numpy.array([0, 0, 0, 1])
                # >>> mathutils.Matrix(numpy.vstack([numpy.hstack([rx, tx]), skew])).decompose()
                # (Vector((1.0, 2.0, 3.0)), Quaternion((1.0, 0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0)))
                translation, rotation, _scale = mathutils.Matrix(numpy.vstack([numpy.hstack([rotation, translation]), skew])).decompose()

                # Now, find the marker in the collection if it exists and make a keyframe for it in the current position.
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
                empty.location = translation
                empty.keyframe_insert(data_path="location", frame=float(frame_idx))  # index=2 would set only z, for example.
                empty.rotation_quaternion = rotation
                empty.keyframe_insert(data_path="rotation_quaternion", frame=float(frame_idx))
            end_time = time.time()
            delta_time = end_time - start_time
            total_time += delta_time
            self.report({'INFO'}, f" ... Done processeing frame {frame_idx} in {delta_time} seconds. Found/updated {len(markers)} markers.")
            # TODO: Reverse the camera one.

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