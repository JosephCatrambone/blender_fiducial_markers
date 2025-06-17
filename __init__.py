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
        col.prop(context.scene.bfm_settings, "dictionary", text="Marker Dictionary")
        col.prop(context.scene.bfm_settings, "generate_2d_tracks")
        col.prop(context.scene.bfm_settings, "empties_at_center")

        _op = layout.operator("bfm.track", text="Run Tracking")

        col = layout.column(heading="Debug", align=True)
        col.operator("bfm.debug_reset", text="DEBUG: Reload the things!")

# Functions:

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

        current_frame = clip.frame_current
        self.report({'INFO'}, f"Processing frame {current_frame}")

        # Example: Process the frame data
        # (This is a placeholder; replace this with your actual data processing logic)
        # You could use clip.tracking.tracks for tracking data
        print(f"Processing frame {current_frame} of clip {clip.name}")

        # Spawn an oriented empty at a specific location
        # For simplicity, we'll just spawn it at the origin
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0, 0, 0))
        empty = context.object
        empty.name = f"Empty_Frame_{current_frame}"
        self.report({'INFO'}, f"Created Empty: {empty.name}")

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