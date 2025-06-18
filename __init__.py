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
import subprocess
import importlib

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
    x_marker: bpy.props.IntProperty(name="+X Marker ID", default=0)  # type: ignore
    y_marker: bpy.props.IntProperty(name="+Y Marker ID", default=0)  # type: ignore
    generate_2d_tracks: bpy.props.BoolProperty(name="Generate 2D Tracking Markers", default=False, description="Generate 2D tracks in addition to the 3D empties.")  # type: ignore
    empties_at_center: bpy.props.BoolProperty(name="Empties at Center", default=True, description="If true, generates empties at the center of the detected markers, else generates them at the top-left corner.")  # type: ignore
    dictionary: bpy.props.StringProperty(name="Fiducial Dictionary")  # type: ignore

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
        col.prop(context.scene.bfm_settings, "x_marker", text="+X Marker ID")
        col.prop(context.scene.bfm_settings, "y_marker", text="+Y Marker ID")

        col = layout.column(heading="Markers", align=True)
        col.prop(context.scene.bfm_settings, "dictionary", text="Dictionary")
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

def iterate_video_frames(
        context: bpy.types.Context,
        data: bpy.types.BlendData,
        movie_clip: bpy.types.MovieClip | str | None = None, 
        start_frame: int | None = None, 
        end_frame: int | None = None
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
    viewer_space.image = image
    for frame_idx in range(start_frame, end_frame):
        viewer_space.image_user.frame_offset = frame_idx
        
        # Force refresh
        viewer_space.display_channels = 'COLOR_ALPHA'
        viewer_space.display_channels = 'COLOR'

        yield(viewer_space.image.pixels)

        #pixels = list(viewer_space.image.pixels)
        #tmp = bpy.data.images.new(name="sample"+str(frame), width=w, height=h, alpha=False, float_buffer=False)
        #tmp.pixels = pixels
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

        for frame_idx, pixel_data in enumerate(iterate_video_frames(context, bpy.data, clip)):
            self.report({'INFO'}, f"Processing frame {frame_idx} with {len(pixel_data)} pixels")
            #__import__('code').interact(local=dict(globals(), **locals()))

        """
        clip.filepath # '//P1000213.MOV'
        img = bpy.data.images.load(clip.filepath)
        clip.frame_offset
        clip.frame_start
        """

        #__import__('code').interact(local=dict(globals(), **locals()))

        # Spawn an oriented empty at a specific location
        # For simplicity, we'll just spawn it at the origin
        #bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
        #empty = context.object
        #empty.name = f"Empty_Frame_{current_frame}"
        #self.report({'INFO'}, f"Created Empty: {empty.name}")

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