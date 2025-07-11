# blender_fiducial_markers
Tracking fiducial markers and reprojecting into 3D space in Blender.

## Installation Instructions:

While this plugin is still in development, it's not packaged and ready-to-go for the normal Blender plugin approach.
Fortunately, the steps are fairly simple and reversible if you want to clear them from your scene.

1. Clone the repository into a directory. We'll use `~/test/python_projects` for our example: `git clone git@github.com:JosephCatrambone/blender_fiducial_markers.git ~/python_projects/blender_fiducial_markers`

2. In your Blender project, open the "Scripting" workspace.  Click the 'new text' button and paste these lines from __init__.py:

```
import sys
import os
import bpy

blend_dir = "/home/test/python_projects/"  # From step 1. This does not include the BFM directory.
if blend_dir not in sys.path:
   sys.path.append(blend_dir)

import importlib
bfm = importlib.import_module("blender_fiducial_markers")
importlib.reload(bfm)
bfm.main()
```

3. Run the script by pressing the 'play' button.

## Usage Instructions:

1. Open the motion tracking workspace and load a movie clip.  

1a. It can be useful to press "Set Scene Frames" under "Clip" so that your timeline has the same number of frames as your video.  

1b. It may also be useful to reset your camera's position and rotation (Alt+G, Alt+R).

2. Under the 'Track' menu, find there's a new section: "Fiducial Markers".  

3. Set your focal distance, marker size, marker type, and other parameters.  

4. Finally, when you're ready, you can press "Run Tracking".  Blender will seem to lock up while the frames are being processed, but eventually you'll end up with a series of animated markers in your collection.

## Known Bugs and Limitations:

1. The UX is suboptimal because of the UI deadlocking. There's more feedback needed on how the process is going.

2. I'm still resolving the difference in coordinate systems for the markers.  In theory, the change of basis is right, but...
