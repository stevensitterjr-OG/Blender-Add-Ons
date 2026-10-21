# Blender 3MF Importer

Adds **File → Import → 3MF (.3mf)** to Blender. No external Python packages are required.

## Install

1. Download `dist/io_mesh_3mf.zip`.
2. In Blender 4.2 or newer, open **Edit → Preferences → Add-ons**.
3. Choose **Install from Disk…** from the top-right menu, select the ZIP, and enable **3MF Importer** if needed.
4. Choose **File → Import → 3MF (.3mf)** and select one or more files.

Tested with Blender **4.3.2** in background mode. Interactive file-browser UI has not been manually tested.

## Behavior

- Imports triangle meshes from 3MF ZIP packages and resolves the package's primary model relationship.
- Honors build items, nested component assemblies, and their rotation/translation/scale transforms.
- Repeated instances share mesh data. Each file gets its own collection; imported objects are selected.
- **Use File Units** (enabled by default) converts micron, millimeter, centimeter, inch, foot, and meter coordinates to the scene's unit scale. With the default scene scale, a 10 mm edge becomes 0.01 Blender units. Disable this option to retain raw coordinates.
- **Scale** applies an additional multiplier to both geometry and placement.
- Supports undo through Blender's import operator.
- Validates each file before creating objects. A malformed file is skipped with a report; successful files in a multiple-file import remain imported.

## Scope

This is a core 3MF geometry importer, not a complete implementation of every 3MF extension. Materials, color, textures, printer settings, and slicer metadata are not imported. A warning is shown when recognized material resources are omitted. Files declaring required extensions, including cross-file production assemblies, are rejected explicitly rather than imported partially. XML parts larger than 256 MiB and component hierarchies deeper than 128 levels are rejected.

## Development

Use the existing checkout; no worktree is needed. Run checks with Blender's embedded Python:

```sh
cd /workspace/Blender-Add-Ons
blender --background --factory-startup --python-exit-code 1 --python tests/test_import_3mf.py
```

Checks exercise real Blender mesh creation, instancing, transforms, units, failure handling, operator registration, selection, and multiple-file import using generated 3MF fixtures. No third-party real-world file corpus is included.

Rebuild the installable ZIP (include the package directory, not just its contents):

```sh
python - <<'PY'
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
Path('dist').mkdir(exist_ok=True)
with ZipFile('dist/io_mesh_3mf.zip', 'w', ZIP_DEFLATED) as archive:
    archive.write('io_mesh_3mf/__init__.py', 'io_mesh_3mf/__init__.py')
PY
```
