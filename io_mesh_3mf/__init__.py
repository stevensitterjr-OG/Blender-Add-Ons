bl_info = {
    "name": "3MF Importer",
    "author": "Blender-Add-Ons contributors",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "File > Import > 3MF (.3mf)",
    "description": "Import 3MF triangle meshes, assemblies, transforms and units",
    "category": "Import-Export",
}

import math
import posixpath
import zipfile
from urllib.parse import unquote
from xml.etree import ElementTree as ET

import bpy
from bpy.props import BoolProperty, CollectionProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS = {"m": CORE}
UNITS = {"micron": 1e-6, "millimeter": .001, "centimeter": .01,
         "inch": .0254, "foot": .3048, "meter": 1.0}
MAX_XML = 256 * 1024 * 1024


def transform(value):
    if not value:
        return Matrix.Identity(4)
    values = [float(v) for v in value.split()]
    if len(values) != 12 or not all(math.isfinite(v) for v in values):
        raise ValueError("Invalid 3MF transform (expected 12 finite numbers)")
    # 3MF uses row vectors; Blender uses column vectors.
    return Matrix(((values[0], values[3], values[6], values[9]),
                   (values[1], values[4], values[7], values[10]),
                   (values[2], values[5], values[8], values[11]),
                   (0, 0, 0, 1)))


def read_model(filepath):
    with zipfile.ZipFile(filepath) as archive:
        def read_xml(path):
            info = archive.getinfo(path)
            if info.file_size > MAX_XML:
                raise ValueError("3MF XML part exceeds the 256 MiB safety limit")
            raw = archive.read(info)
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("DTD/entity declarations are not supported")
            return ET.fromstring(raw)

        model_path = "3D/3dmodel.model"
        if "_rels/.rels" in archive.namelist():
            relationships = read_xml("_rels/.rels")
            for rel in relationships:
                if rel.get("Type", "").endswith("/3dmodel"):
                    if rel.get("TargetMode", "Internal") != "Internal":
                        raise ValueError("External model relationships are unsupported")
                    model_path = posixpath.normpath(unquote(rel.attrib["Target"]).lstrip("/"))
                    break
        root = read_xml(model_path)
    if root.tag != "{" + CORE + "}model":
        raise ValueError("Not a supported 3MF core model")
    # Reject required extensions rather than silently importing incomplete geometry.
    if root.get("requiredextensions", "").strip():
        raise ValueError("This model requires unsupported 3MF extensions: " + root.get("requiredextensions"))
    unit = root.get("unit", "millimeter")
    if unit not in UNITS:
        raise ValueError("Unsupported 3MF unit: " + unit)
    objects = {}
    resources = root.find("m:resources", NS)
    if resources is None:
        raise ValueError("3MF has no resources")
    for node in resources.findall("m:object", NS):
        oid = int(node.attrib["id"])
        if oid in objects:
            raise ValueError("Duplicate object ID")
        objects[oid] = node
    build = root.find("m:build", NS)
    if build is None:
        raise ValueError("3MF has no build")
    meshes = {}
    instances = []

    def visit(oid, matrix, ancestors):
        if len(ancestors) >= 128 or oid in ancestors:
            raise ValueError("Cyclic or excessively deep component hierarchy")
        if oid not in objects:
            raise ValueError("Missing 3MF object: " + str(oid))
        node = objects[oid]
        mesh = node.find("m:mesh", NS)
        components = node.find("m:components", NS)
        if (mesh is None) == (components is None):
            raise ValueError("Object must contain either a mesh or components")
        if mesh is not None:
            if oid not in meshes:
                vertices_node = mesh.find("m:vertices", NS)
                triangles_node = mesh.find("m:triangles", NS)
                if vertices_node is None or triangles_node is None:
                    raise ValueError("Mesh is missing vertices or triangles")
                vertices = [tuple(float(v.attrib[axis]) for axis in ("x", "y", "z"))
                            for v in vertices_node.findall("m:vertex", NS)]
                if not all(math.isfinite(c) for vertex in vertices for c in vertex):
                    raise ValueError("Mesh contains non-finite coordinates")
                faces = [tuple(int(t.attrib[key]) for key in ("v1", "v2", "v3"))
                         for t in triangles_node.findall("m:triangle", NS)]
                if not vertices or not faces:
                    raise ValueError("Mesh has no triangle geometry")
                if any(len(set(f)) != 3 or any(i < 0 or i >= len(vertices) for i in f) for f in faces):
                    raise ValueError("Mesh contains invalid triangle indices")
                meshes[oid] = (vertices, faces)
            instances.append((oid, node.get("name") or "Object_" + str(oid), matrix))
        else:
            children = components.findall("m:component", NS)
            if not children:
                raise ValueError("Empty component assembly")
            for child in children:
                if any(key.rsplit("}", 1)[-1] == "path" for key in child.attrib):
                    raise ValueError("Cross-file components are unsupported")
                visit(int(child.attrib["objectid"]), matrix @ transform(child.get("transform")), ancestors + (oid,))

    for item in build.findall("m:item", NS):
        if any(key.rsplit("}", 1)[-1] == "path" for key in item.attrib):
            raise ValueError("Cross-file build items are unsupported")
        visit(int(item.attrib["objectid"]), transform(item.get("transform")), ())
    if not instances:
        raise ValueError("3MF build has no mesh instances")
    has_properties = any(node.tag.rsplit("}", 1)[-1] in {
        "basematerials", "colorgroup", "texture2d", "texture2dgroup", "multiproperties"
    } for node in resources)
    return meshes, instances, UNITS[unit], has_properties


def import_file(context, filepath, global_scale=1.0, use_file_units=True):
    meshes, instances, unit, has_properties = read_model(filepath)
    scale = global_scale * (unit / context.scene.unit_settings.scale_length if use_file_units else 1.0)
    collection = None
    created_meshes = []
    created_objects = []
    try:
        collection = bpy.data.collections.new(bpy.path.display_name_from_filepath(filepath))
        context.collection.children.link(collection)
        data = {}
        for oid, (vertices, faces) in meshes.items():
            mesh = bpy.data.meshes.new("3MF_" + str(oid))
            created_meshes.append(mesh)
            mesh.from_pydata(vertices, [], faces)
            mesh.update()
            data[oid] = mesh
        for oid, name, matrix in instances:
            obj = bpy.data.objects.new(name, data[oid])
            created_objects.append(obj)
            collection.objects.link(obj)
            obj.matrix_world = Matrix.Scale(scale, 4) @ matrix
    except Exception:
        for obj in created_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in created_meshes:
            bpy.data.meshes.remove(mesh)
        if collection is not None:
            bpy.data.collections.remove(collection)
        raise
    return created_objects, has_properties


class IMPORT_SCENE_OT_3mf(bpy.types.Operator, ImportHelper):
    bl_idname = "import_mesh.threemf"
    bl_label = "Import 3MF"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".3mf"
    filter_glob: StringProperty(default="*.3mf", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH")
    global_scale: FloatProperty(name="Scale", default=1.0, min=0.000001, max=1e6)
    use_file_units: BoolProperty(name="Use File Units", default=True,
                                description="Convert 3MF units to the scene's unit scale")

    def execute(self, context):
        import os
        paths = [os.path.join(self.directory, f.name) for f in self.files] if self.files else [self.filepath]
        imported = []
        failures = 0
        for path in paths:
            try:
                objects, has_properties = import_file(context, path, self.global_scale, self.use_file_units)
                imported.extend(objects)
                if has_properties:
                    self.report({"WARNING"}, "Imported geometry only; material/color/texture properties were omitted")
            except (ValueError, KeyError, OSError, RuntimeError, ET.ParseError, zipfile.BadZipFile, OverflowError, RecursionError) as exc:
                failures += 1
                self.report({"WARNING"}, os.path.basename(path) + ": " + str(exc))
        if not imported:
            self.report({"ERROR"}, "No 3MF geometry imported; check the file or unsupported extensions")
            return {"CANCELLED"}
        for obj in context.view_layer.objects:
            obj.select_set(False)
        for obj in imported:
            obj.select_set(True)
        context.view_layer.objects.active = imported[-1]
        self.report({"INFO"}, f"Imported {len(imported)} mesh object(s); {failures} file(s) failed")
        return {"FINISHED"}


def menu_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_3mf.bl_idname, text="3MF (.3mf)")


def register():
    bpy.utils.register_class(IMPORT_SCENE_OT_3mf)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.utils.unregister_class(IMPORT_SCENE_OT_3mf)


if __name__ == "__main__":
    register()
