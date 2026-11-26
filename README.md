# Vertex Group Mirror Modifier addon for Blender
Mirror Modifier for Blender, using geometry nodes to restrict its effects to a set vertex group

Use: Select a mesh, then go to Modifiers → Add Modifier → Generate → Mirror (Vertex Group). If the object has an active vertex group, it's picked automatically.

Settings:

- Axis X / Y / Z work like the stock modifier. Axes are applied in order X, Y, Z, each on the result of the previous one.
- Mirror Object: mirrors around that object's origin and rotation, as the stock modifier does.
- Group: has a small icon next to the field. Click it to choose a group from a dropdown. With the icon off, everything is mirrored, so the modifier behaves like a normal Mirror.
- Invert mirrors everything not in the group.
- Threshold is the weight a vertex must exceed to count as "in" the group.
- Merge and Merge Distance weld vertices to their mirror images, but only along the mirror seam, so unrelated nearby vertices aren't welded.
