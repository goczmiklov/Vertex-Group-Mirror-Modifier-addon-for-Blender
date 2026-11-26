# SPDX-License-Identifier: GPL-3.0-or-later
#
# Vertex Group Mirror Modifier
# ----------------------------
# Adds a "Mirror (Vertex Group)" entry to the Add Modifier menu. It behaves like
# the built-in Mirror modifier (X/Y/Z axes, mirror object, merge) but adds a
# Vertex Group input: only the part of the mesh inside that group gets mirrored.
#
# Blender's Python API cannot register brand-new *native* modifier types, so this
# add-on builds the modifier as a Geometry Nodes modifier. It is a real modifier
# on the stack (you can reorder it, apply it, show/hide it, etc.), and the node
# group it uses is fully editable if you want to tweak it.

bl_info = {
    "name": "Vertex Group Mirror Modifier",
    "author": "Claude",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "Properties > Modifiers > Add Modifier > Generate > Mirror (Vertex Group)",
    "description": "A Mirror modifier that can be restricted to a vertex group",
    "category": "Object",
}

import bpy
from bpy.types import Operator

GROUP_NAME = "Mirror (Vertex Group)"
GROUP_VERSION = 1  # bump if the node tree layout changes
VERSION_KEY = "vgmirror_version"


# --------------------------------------------------------------------------- #
#  Small helpers to stay compatible across Blender versions
# --------------------------------------------------------------------------- #

def _sock(sockets, name, idname=None, output=False):
    """Find the first enabled socket called `name` (optionally of a given type)."""
    fallback = None
    for s in sockets:
        if s.name != name:
            continue
        if fallback is None:
            fallback = s
        if not s.enabled:
            continue
        if idname is None or s.bl_idname.startswith(idname):
            return s
    return fallback


def _set_enum(node, socket_name, prop_name, value_socket, value_prop):
    """Set an enum that is a menu *socket* in newer Blender, a node property in older."""
    sock = node.inputs.get(socket_name)
    if sock is not None and sock.bl_idname == "NodeSocketMenu":
        sock.default_value = value_socket
    elif hasattr(node, prop_name):
        setattr(node, prop_name, value_prop)


def _new(nodes, idname, x, y, label=None):
    n = nodes.new(idname)
    n.location = (x, y)
    if label:
        n.label = label
    return n


# --------------------------------------------------------------------------- #
#  Node group construction
# --------------------------------------------------------------------------- #

def build_node_group():
    ng = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    ng[VERSION_KEY] = GROUP_VERSION
    if hasattr(ng, "is_modifier"):
        ng.is_modifier = True
    if hasattr(ng, "is_tool"):
        ng.is_tool = False

    iface = ng.interface

    # ---- Interface ------------------------------------------------------- #
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

    def add_in(name, socket_type, default=None, desc="", parent=None,
               min_value=None, max_value=None, domain=None, subtype=None):
        kwargs = dict(in_out="INPUT", socket_type=socket_type, description=desc)
        if parent is not None:
            kwargs["parent"] = parent
        s = iface.new_socket(name, **kwargs)
        if subtype is not None:
            try:
                s.subtype = subtype
            except (TypeError, AttributeError):
                pass
        if default is not None:
            s.default_value = default
        if min_value is not None:
            s.min_value = min_value
        if max_value is not None:
            s.max_value = max_value
        if domain is not None and hasattr(s, "attribute_domain"):
            s.attribute_domain = domain
        return s

    add_in("Axis X", "NodeSocketBool", True, "Mirror along the X axis")
    add_in("Axis Y", "NodeSocketBool", False, "Mirror along the Y axis")
    add_in("Axis Z", "NodeSocketBool", False, "Mirror along the Z axis")
    add_in("Mirror Object", "NodeSocketObject", None,
           "Mirror around this object's origin and axes instead of the modified "
           "object's own origin")

    vg_panel = iface.new_panel("Vertex Group")
    vg = add_in("Vertex Group", "NodeSocketFloat", 1.0,
                "Only geometry in this vertex group is mirrored. Click the small "
                "icon next to the field and pick a group. With the icon off, "
                "everything is mirrored (like the regular Mirror modifier)",
                parent=vg_panel, min_value=0.0, max_value=1.0, domain="POINT",
                subtype="FACTOR")
    add_in("Invert", "NodeSocketBool", False,
           "Mirror everything that is NOT in the vertex group", parent=vg_panel)
    add_in("Threshold", "NodeSocketFloat", 0.0,
           "A vertex counts as 'in the group' if its weight is above this value",
           parent=vg_panel, min_value=0.0, max_value=1.0, subtype="FACTOR")

    merge_panel = iface.new_panel("Merge")
    add_in("Merge", "NodeSocketBool", True,
           "Merge vertices that lie close to their mirrored counterparts",
           parent=merge_panel)
    add_in("Merge Distance", "NodeSocketFloat", 0.001,
           "Maximum distance between a vertex and its mirror image for them to merge",
           parent=merge_panel, min_value=0.0, subtype="DISTANCE")

    # ---- Nodes ----------------------------------------------------------- #
    nodes, links = ng.nodes, ng.links
    nodes.clear()

    gin = _new(nodes, "NodeGroupInput", -1400, 0)
    gout = _new(nodes, "NodeGroupOutput", 1500, 0)

    def gi(name):
        return gin.outputs[name]

    # Mirror object transform (relative to the modified object)
    objinfo = _new(nodes, "GeometryNodeObjectInfo", -1150, -350, "Mirror Object")
    objinfo.transform_space = "RELATIVE"
    links.new(gi("Mirror Object"), objinfo.inputs["Object"])
    obj_xf = objinfo.outputs["Transform"]

    inv = _new(nodes, "FunctionNodeInvertMatrix", -900, -450)
    links.new(obj_xf, inv.inputs[0])

    # Which vertices are "in the group"?
    cmp_thr = _new(nodes, "FunctionNodeCompare", -1150, 250, "Weight > Threshold")
    cmp_thr.data_type = "FLOAT"
    cmp_thr.operation = "GREATER_THAN"
    links.new(gi("Vertex Group"), _sock(cmp_thr.inputs, "A", "NodeSocketFloat"))
    links.new(gi("Threshold"), _sock(cmp_thr.inputs, "B", "NodeSocketFloat"))

    xor = _new(nodes, "FunctionNodeBooleanMath", -900, 250, "Invert?")
    xor.operation = "XOR"
    links.new(cmp_thr.outputs["Result"], xor.inputs[0])
    links.new(gi("Invert"), xor.inputs[1])
    in_group = xor.outputs["Boolean"]

    position = _new(nodes, "GeometryNodeInputPosition", -900, -650)

    def mirror_stage(geo_socket, axis_index, axis_name, x0):
        """Mirror the selected part of `geo_socket` across one axis and join it."""
        # axis_on AND in_group
        sel = _new(nodes, "FunctionNodeBooleanMath", x0, 250, f"{axis_name}: select")
        sel.operation = "AND"
        links.new(in_group, sel.inputs[0])
        links.new(gi(f"Axis {axis_name}"), sel.inputs[1])

        # Reflection matrix = ObjectXf * Scale(-1 on axis) * inverse(ObjectXf)
        flip = _new(nodes, "FunctionNodeCombineTransform", x0, -300, f"{axis_name}: flip")
        scale = [1.0, 1.0, 1.0]
        scale[axis_index] = -1.0
        flip.inputs["Scale"].default_value = scale

        m1 = _new(nodes, "FunctionNodeMatrixMultiply", x0 + 180, -300)
        links.new(obj_xf, m1.inputs[0])
        links.new(flip.outputs[0], m1.inputs[1])
        m2 = _new(nodes, "FunctionNodeMatrixMultiply", x0 + 360, -300)
        links.new(m1.outputs[0], m2.inputs[0])
        links.new(inv.outputs[0], m2.inputs[1])
        reflect = m2.outputs[0]

        # Pull out the part to mirror
        sep = _new(nodes, "GeometryNodeSeparateGeometry", x0 + 180, 100, f"{axis_name}: part")
        sep.domain = "POINT"
        links.new(geo_socket, sep.inputs["Geometry"])
        links.new(sel.outputs["Boolean"], sep.inputs["Selection"])

        xf = _new(nodes, "GeometryNodeTransform", x0 + 400, 100, f"{axis_name}: mirror")
        _set_enum(xf, "Mode", "mode", "Matrix", "MATRIX")
        links.new(sep.outputs["Selection"], xf.inputs["Geometry"])
        links.new(reflect, _sock(xf.inputs, "Transform", "NodeSocketMatrix"))

        # A mirrored mesh has reversed winding, so flip the faces back
        ff = _new(nodes, "GeometryNodeFlipFaces", x0 + 580, 100)
        links.new(xf.outputs["Geometry"], ff.inputs[0])

        join = _new(nodes, "GeometryNodeJoinGeometry", x0 + 760, 0, f"{axis_name}: join")
        links.new(geo_socket, join.inputs[0])
        links.new(ff.outputs[0], join.inputs[0])

        # Merge only vertices that sit right next to their own mirror image
        refl_pt = _new(nodes, "FunctionNodeTransformPoint", x0 + 540, -400)
        links.new(position.outputs[0], refl_pt.inputs["Vector"])
        links.new(reflect, refl_pt.inputs["Transform"])
        diff = _new(nodes, "ShaderNodeVectorMath", x0 + 720, -400)
        diff.operation = "DISTANCE"
        links.new(position.outputs[0], diff.inputs[0])
        links.new(refl_pt.outputs[0], diff.inputs[1])
        near = _new(nodes, "FunctionNodeCompare", x0 + 900, -400, "Near mirror image")
        near.data_type = "FLOAT"
        near.operation = "LESS_EQUAL"
        links.new(diff.outputs["Value"], _sock(near.inputs, "A", "NodeSocketFloat"))
        links.new(gi("Merge Distance"), _sock(near.inputs, "B", "NodeSocketFloat"))
        do_merge = _new(nodes, "FunctionNodeBooleanMath", x0 + 900, -250)
        do_merge.operation = "AND"
        links.new(near.outputs["Result"], do_merge.inputs[0])
        links.new(sel.outputs["Boolean"], do_merge.inputs[1])
        do_merge2 = _new(nodes, "FunctionNodeBooleanMath", x0 + 1080, -250)
        do_merge2.operation = "AND"
        links.new(do_merge.outputs[0], do_merge2.inputs[0])
        links.new(gi("Merge"), do_merge2.inputs[1])

        merge = _new(nodes, "GeometryNodeMergeByDistance", x0 + 1080, 0, f"{axis_name}: merge")
        _set_enum(merge, "Mode", "mode", "All", "ALL")
        links.new(join.outputs[0], merge.inputs["Geometry"])
        links.new(do_merge2.outputs[0], merge.inputs["Selection"])
        links.new(gi("Merge Distance"), merge.inputs["Distance"])
        return merge.outputs[0]

    geo = gi("Geometry")
    # Same behaviour as the stock modifier: X, then Y (of the result), then Z.
    for i, axis in enumerate("XYZ"):
        geo = mirror_stage(geo, i, axis, -650 + i * 1500)
    gout.location = (-650 + 3 * 1500, 0)
    links.new(geo, gout.inputs[0])
    return ng


def get_node_group():
    ng = bpy.data.node_groups.get(GROUP_NAME)
    if ng is not None and ng.get(VERSION_KEY) is not None:
        return ng
    return build_node_group()


# --------------------------------------------------------------------------- #
#  Operator + menu
# --------------------------------------------------------------------------- #

def _socket_identifier(ng, name):
    for item in ng.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == name:
            return item.identifier
    return None


class OBJECT_OT_add_vertex_group_mirror(Operator):
    """Add a Mirror modifier that can be restricted to a vertex group"""
    bl_idname = "object.add_vertex_group_mirror_modifier"
    bl_label = "Mirror (Vertex Group)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type in {"MESH"} and ob.library is None

    def execute(self, context):
        ob = context.object
        ng = get_node_group()

        mod = ob.modifiers.new(name="Mirror (Vertex Group)", type="NODES")
        mod.node_group = ng

        # Use the object's active vertex group straight away, if it has one.
        vg_id = _socket_identifier(ng, "Vertex Group")
        if vg_id and ob.vertex_groups.active is not None:
            key = vg_id + "_use_attribute"
            # Boolean IDProperty in recent versions, int in older ones
            mod[key] = type(mod[key])(1) if key in mod else True
            mod[vg_id + "_attribute_name"] = ob.vertex_groups.active.name

        ob.modifiers.active = mod
        ob.update_tag()
        context.view_layer.update()
        return {"FINISHED"}


def _menu_func(self, context):
    self.layout.operator(OBJECT_OT_add_vertex_group_mirror.bl_idname,
                         text="Mirror (Vertex Group)", icon="MOD_MIRROR")


def _menu_type():
    """The 'Generate' submenu where the stock Mirror modifier lives."""
    return (getattr(bpy.types, "OBJECT_MT_modifier_add_generate", None)
            or getattr(bpy.types, "OBJECT_MT_modifier_add", None))


def register():
    bpy.utils.register_class(OBJECT_OT_add_vertex_group_mirror)
    menu = _menu_type()
    if menu is not None:
        menu.append(_menu_func)


def unregister():
    menu = _menu_type()
    if menu is not None:
        menu.remove(_menu_func)
    bpy.utils.unregister_class(OBJECT_OT_add_vertex_group_mirror)


if __name__ == "__main__":
    register()
