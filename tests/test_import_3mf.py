"""Run with Blender: blender -b --factory-startup --python-exit-code 1 --python tests/test_import_3mf.py"""
import sys
import tempfile
import zipfile
from pathlib import Path

import bpy
from mathutils import Vector
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io_mesh_3mf as addon

MESH = '''<object id="1" name="Triangle" type="model"><mesh><vertices>
<vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="0"/>
</vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>'''

def model(resources=MESH, build='<item objectid="1"/>', unit="millimeter", extra=""):
    return f'<model xmlns="{addon.CORE}" unit="{unit}" {extra}><resources>{resources}</resources><build>{build}</build></model>'


def write(path, xml, custom=False):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        name = 'Models/part.model' if custom else '3D/3dmodel.model'
        z.writestr(name, xml)
        if custom:
            z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/Models/part.model"/></Relationships>')


def near(a, b):
    assert (Vector(a) - Vector(b)).length < 1e-6, (a, b)


addon.register()
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'sample.3mf'
    assembly = '<object id="2"><components><component objectid="1" transform="1 0 0 0 1 0 0 0 1 5 0 0"/></components></object>'
    write(path, model(MESH + assembly, '<item objectid="2" transform="0 1 0 -1 0 0 0 0 1 0 20 0"/><item objectid="1"/>'), custom=True)
    objects, properties = addon.import_file(bpy.context, str(path))
    assert len(objects) == 2 and not properties
    assert objects[0].data is objects[1].data
    near(objects[0].matrix_world @ objects[0].data.vertices[1].co, (0, .035, 0))
    assert len(objects[0].data.polygons) == 1
    print('PASS: package relationship, assembly, rotation, translation, linked mesh, millimeters')

    bpy.context.scene.unit_settings.scale_length = .01
    write(path, model(unit='inch'))
    objects, _ = addon.import_file(bpy.context, str(path))
    near(objects[0].matrix_world @ objects[0].data.vertices[1].co, (25.4, 0, 0))
    objects, _ = addon.import_file(bpy.context, str(path), global_scale=2, use_file_units=False)
    near(objects[0].matrix_world @ objects[0].data.vertices[1].co, (20, 0, 0))
    print('PASS: inches, scene unit scale, raw units, global scale')

    bad_models = [model(MESH.replace('v3="2"', 'v3="99"')),
                  model('<object id="1"><components><component objectid="1"/></components></object>'),
                  model(build='<item objectid="99"/>'), model(extra='requiredextensions="p"'),
                  model(build='<item objectid="1" transform="1 2"/>'),
                  model(MESH.replace('x="10"', 'x="nan"'))]
    for xml in bad_models:
        write(path, xml)
        before = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.collections))
        try:
            addon.import_file(bpy.context, str(path))
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid input accepted')
        assert before == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.collections))
    print('PASS: six invalid models rejected without scene changes')

    write(path, model())
    result = bpy.ops.import_mesh.threemf(filepath=str(path))
    assert result == {'FINISHED'}
    assert bpy.context.view_layer.objects.active.select_get()
    result = bpy.ops.import_mesh.threemf(directory=temp, files=[{'name': path.name}, {'name': path.name}])
    assert result == {'FINISHED'}
    assert len(bpy.context.selected_objects) == 2
    print('PASS: registered file import operator, selection, multi-file import')
addon.unregister()
addon.register()
addon.unregister()
print('ALL 3MF IMPORT CHECKS PASSED')
