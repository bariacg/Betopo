# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Real BMesh construction, curved projection, attachment and safe redrawing."""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if not bpy.app.background or bpy.app.version[:2] != (5,1):
    raise RuntimeError('Use isolated Blender 5.1 --background --factory-startup')
(ROOT/'.test-output').mkdir(exist_ok=True)
import betopo
from betopo import area, core, flow

betopo.register()
bpy.context.preferences.use_preferences_save = False
results = []


def check(name, condition):
    assert condition, name
    results.append(name)
    print('AREA FLOW CORE PASS', name, flush=True)


def rejects(name, operation):
    try:
        operation()
    except ValueError:
        check(name, True)
    else:
        raise AssertionError(name)


def target():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    obj = bpy.data.objects.new('Area Flow Test', bpy.data.meshes.new('Area Flow Test'))
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.matrix_world = Matrix.Translation((3, -2, 0)) @ Matrix.Diagonal((2, 2, 2, 1))
    bpy.context.scene.betopo.target = obj
    bpy.ops.object.mode_set(mode='EDIT')
    return obj, bmesh.from_edit_mesh(obj.data)


def guides(corners):
    return [dict(points=[Vector(a), Vector(b)]) for a,b in zip(corners,corners[1:]+corners[:1])]


bpy.ops.mesh.primitive_plane_add(size=40)
source_obj = bpy.context.active_object
source_before = [tuple(v.co) for v in source_obj.data.vertices]
surface = core.SourceSurface(source_obj,bpy.context.evaluated_depsgraph_get())
obj,bm = target()
square = guides([(-2,-1,0),(2,-1,0),(2,1,0),(-2,1,0)])
plan = area.grid_plan(square,.5,surface)
check('Area density makes an 8 x 4 grid', (plan['grid_columns'],plan['grid_rows']) == (8,4))
vertices,faces = core.add_patch(obj,bm,plan,surface)
check('Area builds real quad faces on a transformed target', len(vertices)==45 and len(faces)==32 and all(len(f.verts)==4 for f in bm.faces))
check('Area does not modify its guide inputs', tuple(square[0]['points'][0]) == (-2,-1,0))
check('Area preserves world positions with target transforms', all((obj.matrix_world@v.co-p).length<1e-6 for v,p in zip(vertices,plan['points'])))
explicit = area.grid_plan(square,.5,surface,.1,(3,2))
check('Area manual subdivision overrides density and projects offset', len(explicit['faces'])==6 and all(abs(p.z-.1)<1e-6 for p in explicit['points']))
bad = guides([(-1,-1,0),(1,1,0),(-1,1,0),(1,-1,0)])
rejects('Area rejects crossed boundaries', lambda: area.grid_plan(bad,.2,surface))
rejects('Area rejects an unsafe density', lambda: area.grid_plan(square,.00001,surface))
bad_gap = guides([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)])
bad_gap[3]['points'][-1] += Vector((1,0,0))
rejects('Area rejects disconnected sides', lambda: area.grid_plan(bad_gap,.2,surface))
before_counts = (len(bm.verts),len(bm.edges),len(bm.faces))
tiny = area.grid_plan(guides([(-2,-1,0),(-1.99,-1,0),(-1.99,-.99,0),(-2,-.99,0)]),.02,surface)
rejects('Collapsed weld is rejected atomically', lambda: core.add_patch(obj,bm,tiny,surface,100))
check('Failed construction leaves the existing mesh intact', (len(bm.verts),len(bm.edges),len(bm.faces))==before_counts)

obj,bm = target()
inverse = obj.matrix_world.inverted_safe()
rim = [bm.verts.new(inverse@Vector(p)) for p in ((-1,0,0),(0,0,0),(1,0,0))]
for a,b in zip(rim,rim[1:]):
    bm.edges.new((a,b))
attached = guides([(-1,0,0),(1,0,0),(1,2,0),(-1,2,0)])
attached[0] = dict(points=[obj.matrix_world@v.co for v in rim],existing=rim)
plan = area.grid_plan(attached,.25,surface,subdivisions=(20,4))
check('Area keeps attached boundary count despite column override', plan['grid_columns']==2 and len(plan['existing'])==3)
vertices,faces = core.add_patch(obj,bm,plan,surface)
check('Area reuses actual boundary vertices without duplicates', set(rim)<=set(vertices) and len(bm.verts)==15 and len(faces)==8)
opposite = [bm.verts.new(inverse@Vector(p)) for p in ((1,2,0),(-1,2,0))]
attached[2] = dict(points=[obj.matrix_world@v.co for v in opposite],existing=opposite)
rejects('Area rejects incompatible opposite boundaries', lambda: area.grid_plan(attached,.25,surface))

obj,bm = target()
stroke = [Vector((0,0,0)),Vector((.4,1,0)),Vector((0,2,0))]
pin = bm.verts.layers.int.new('betopo_pin')
plan = flow.ribbon_plan(stroke,8,.3,surface,smooth=.5)
vertices,faces = core.add_patch(obj,bm,plan,surface)
check('Flow builds a one-quad-wide smooth strip', len(vertices)==18 and len(faces)==8 and all(len(f.verts)==4 for f in faces))
state = flow.record(obj,vertices,faces,plan)
redraw = flow.ribbon_plan([(0,0,0),(-.4,1,0),(0,2,0)],8,.4,surface,smooth=.5)
before_positions = [v.co.copy() for v in vertices]
flow.apply_redraw(obj,bm,state,redraw)
check('Flow redraw moves the strip without changing topology', len(bm.verts)==18 and len(bm.faces)==8 and any((v.co-p).length>.01 for v,p in zip(vertices,before_positions)))
vertices[4][pin] = 1
rejects('Flow redraw respects pinned vertices', lambda: flow.apply_redraw(obj,bm,state,redraw))
vertices[4][pin] = 0
extra = [bm.verts.new(v.co+Vector((0,0,1))) for v in vertices[2:4]]
bm.faces.new((vertices[2],extra[0],extra[1],vertices[3]))
rejects('Flow redraw rejects a strip joined to other faces', lambda: flow.check_record(state,obj))

obj,bm = target()
fixture = [bm.verts.new(obj.matrix_world.inverted_safe()@Vector(p)) for p in
           ((-.3,-1,0),(.3,-1,0),(.3,0,0),(-.3,0,0))]
bm.faces.new(fixture)
start = (fixture[3],fixture[2])
plan = flow.ribbon_plan([(0,0,0),(.2,1,0),(0,2,0)],6,.4,surface,obj=obj,start=start)
vertices,faces = core.add_patch(obj,bm,plan,surface)
check('Flow attaches to a border with a shared manifold edge', set(vertices[:2])==set(start) and len(bm.edges.get(start).link_faces)==2 and len(bm.verts)==16)
state = flow.record(obj,vertices,faces,plan)
anchor_coords = [v.co.copy() for v in start]
redraw = flow.ribbon_plan([(0,2,0),(-.2,1,0),(0,0,0)],6,.3,surface,obj=obj,
                          start=state['start'],fixed_order=True)
flow.apply_redraw(obj,bm,state,redraw)
check('Attached redraw accepts a reversed stroke and fixes anchors', all((v.co-p).length<1e-8 for v,p in zip(start,anchor_coords)))

obj,bm = target()
inv=obj.matrix_world.inverted_safe()
fixture=[]
for coords in (((-.3,-1,0),(.3,-1,0),(.3,0,0),(-.3,0,0)),
               ((-.3,2,0),(.3,2,0),(.3,3,0),(-.3,3,0))):
    row=[bm.verts.new(inv@Vector(p)) for p in coords]
    bm.faces.new(row)
    fixture.append(row)
start=(fixture[0][3],fixture[0][2])
end=(fixture[1][1],fixture[1][0])
plan=flow.ribbon_plan([(0,0,0),(.2,1,0),(0,2,0)],8,.5,surface,obj=obj,start=start,end=end)
flow.check_attachment(obj,bm,plan,surface)
vertices,faces=core.add_patch(obj,bm,plan,surface)
check('Flow connects both border ends without duplicates',len(bm.verts)==22 and all(len(bm.edges.get(e).link_faces)==2 for e in (start,end)))
state=flow.record(obj,vertices,faces,plan)
anchors={v:v.co.copy() for v in state['anchors']}
redraw=flow.ribbon_plan([(0,2,0),(-.2,1,0),(0,0,0)],8,.4,surface,obj=obj,
                        start=state['start'],end=state['end'],fixed_order=True)
flow.apply_redraw(obj,bm,state,redraw)
check('Flow redraw preserves both attached end edges',all((v.co-co).length<1e-7 for v,co in anchors.items()))

obj,bm = target()
fixture=[bm.verts.new(obj.matrix_world.inverted_safe()@Vector(p)) for p in
         ((-.3,-1,0),(.3,-1,0),(.3,0,0),(-.3,0,0))]
bm.faces.new(fixture)
inward=flow.ribbon_plan([(0,0,0),(0,-.8,0)],6,.3,surface,obj=obj,start=(fixture[3],fixture[2]))
rejects('Inward attachment is rejected before mesh construction',lambda:flow.check_attachment(obj,bm,inward,surface))

obj,bm = target()
circle = [(2*math.cos(i*math.tau/32),2*math.sin(i*math.tau/32),0) for i in range(33)]
plan = flow.ribbon_plan(circle,24,.25,surface,closed=True)
vertices,faces = core.add_patch(obj,bm,plan,surface)
check('Closed Flow has a welded cyclic seam', len(vertices)==48 and len(faces)==24 and sum(e.is_boundary for e in bm.edges)==48)
rejects('Flow rejects a collapsed stroke', lambda: flow.ribbon_plan([(0,0,0),(0,0,0)],8,.2,surface))
rejects('Flow rejects closing an attached ribbon', lambda: flow.ribbon_plan(stroke,8,.2,surface,obj=obj,start=vertices[:2],closed=True))

bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.mesh.primitive_uv_sphere_add(segments=64,ring_count=32,radius=2)
sphere = bpy.context.active_object
curved_surface = core.SourceSurface(sphere,bpy.context.evaluated_depsgraph_get())
corners = [Vector((x,y,math.sqrt(4-x*x-y*y))) for x,y in ((-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5))]
curved = guides(corners)
plan = area.grid_plan(curved,.2,curved_surface,.03)
obj,bm = target()
vertices,faces = core.add_patch(obj,bm,plan,curved_surface)
check('Area makes curved-surface quads with an offset', len(faces)>=25 and all(abs((p-curved_surface.nearest(p)[0]).length-.03)<.003 for p in plan['points']))
curved_stroke = [(2*math.sin(t),0,2*math.cos(t)) for t in (-.4,-.2,0,.2,.4)]
plan = flow.ribbon_plan(curved_stroke,12,.2,curved_surface,.03)
obj,bm = target()
vertices,faces = core.add_patch(obj,bm,plan,curved_surface)
check('Flow follows a curved sculpt with surface offset', len(faces)==12 and all(abs((p-curved_surface.nearest(p)[0]).length-.03)<.003 for p in plan['points']))
check('Source mesh remains unchanged', [tuple(v.co) for v in source_obj.data.vertices]==source_before)

(ROOT/'.test-output/area-flow-core-results.json').write_text(json.dumps({'status':'passed','checks':results},indent=2),encoding='utf-8')
print('AREA FLOW CORE COMPLETE',len(results),flush=True)
betopo.unregister()
