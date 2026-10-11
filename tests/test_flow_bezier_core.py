# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Cubic Flow geometry, surface projection and safe redraw on real Blender BMesh."""
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if not bpy.app.background or bpy.app.version[:2] != (5,1):
    raise RuntimeError('Use isolated Blender 5.1 --background --factory-startup')
(ROOT/'.test-output').mkdir(exist_ok=True)
import betopo
from betopo import core,flow

bpy.context.preferences.use_preferences_save = False
betopo.register()
results = []


def check(name,condition):
    assert condition,name
    results.append(name)
    print('BEZIER CORE PASS',name,flush=True)


def rejects(name,operation):
    try:
        operation()
    except ValueError:
        check(name,True)
    else:
        raise AssertionError(name)


def target():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    obj = bpy.data.objects.new('Bezier Test',bpy.data.meshes.new('Bezier Test'))
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.matrix_world = Matrix.Translation((3,-2,0))@Matrix.Diagonal((2,2,2,1))
    bpy.context.scene.betopo.target = obj
    bpy.ops.object.mode_set(mode='EDIT')
    return obj,bmesh.from_edit_mesh(obj.data)


bpy.ops.mesh.primitive_plane_add(size=40)
source_obj = bpy.context.active_object
source_before = [tuple(v.co) for v in source_obj.data.vertices]
surface = core.SourceSurface(source_obj,bpy.context.evaluated_depsgraph_get())
controls = flow.default_controls((0,0,0),(0,2,0))
check('Default handles trisect the line between exactly two endpoints',
      len(controls)==4 and (controls[1]-Vector((0,2/3,0))).length<1e-7)
controls[1].x = controls[2].x = 1
before = [p.copy() for p in controls]
plan = flow.bezier_plan(controls,12,.2,surface)
check('Cubic midpoint responds to both tangent handles',
      (plan['curve'][len(plan['curve'])//2]-Vector((.75,1,0))).length<1e-6)
check('Bezier planning does not mutate input controls',all(p==q for p,q in zip(controls,before)))
check('Segment count controls topology independently of curve display sampling',
      len(plan['faces'])==12 and len(plan['points'])==26 and len(plan['curve'])==97)
centers=[(a+b)*.5 for a,b in zip(plan['points'][::2],plan['points'][1::2])]
lengths=[(a-b).length for a,b in zip(centers,centers[1:])]
check('Quad rows are sampled at approximately equal arc-length intervals',max(lengths)/min(lengths)<1.04)
obj,bm=target()
vertices,faces=core.add_patch(obj,bm,plan,surface)
check('Bezier creates actual quads with transformed target coordinates',
      len(vertices)==26 and len(faces)==12 and all((obj.matrix_world@v.co-p).length<1e-6 for v,p in zip(vertices,plan['points'])))
rejects('Coincident endpoints are rejected',lambda: flow.default_controls((0,0,0),(0,0,0)))
rejects('Non-finite handles are rejected',lambda: flow.bezier_plan([(0,0,0),(float('nan'),0,0),(0,1,0),(0,2,0)],8,.2,surface))
rejects('More than two endpoints and two handles are rejected',lambda: flow.bezier_plan(controls+[Vector()],8,.2,surface))
rejects('Fractional segments are rejected',lambda: flow.bezier_plan(controls,2.5,.2,surface))
rejects('Non-positive width is rejected',lambda: flow.bezier_plan(controls,8,0,surface))
zero = [Vector((0,0,0)),Vector((0,0,0)),Vector((0,2,0)),Vector((0,2,0))]
check('Zero-length tangent handles still create a straight strip',len(flow.bezier_plan(zero,8,.2,surface)['faces'])==8)
check('One segment remains supported',len(flow.bezier_plan(controls,1,.2,surface)['faces'])==1)
check('Maximum segments have bounded sampling',len(flow.bezier_plan(controls,256,.2,surface)['curve'])==2049)
rejects('Folded wide ribbons are rejected before building mesh',lambda: flow.bezier_plan(controls,16,10,surface))

obj,bm=target()
pin=bm.verts.layers.int.new('betopo_pin')
inverse=obj.matrix_world.inverted_safe()
rim=[]
for coords in (((-.15,-1,0),(.15,-1,0),(.15,0,0),(-.15,0,0)),
               ((-.15,2,0),(.15,2,0),(.15,3,0),(-.15,3,0))):
    row=[bm.verts.new(inverse@Vector(p)) for p in coords]
    bm.faces.new(row)
    rim.append(row)
start,end=(rim[0][3],rim[0][2]),(rim[1][1],rim[1][0])
controls=flow.default_controls((.2,0,0),(.2,2,0))
plan=flow.bezier_plan(controls,8,.3,surface,obj=obj,start=start,end=end)
check('Attaching an endpoint translates its tangent by the same amount',
      (plan['flow_controls'][0]-Vector((0,0,0))).length<1e-6 and
      ((plan['flow_controls'][1]-plan['flow_controls'][0])-(controls[1]-controls[0])).length<1e-6)
flow.check_attachment(obj,bm,plan,surface)
vertices,faces=core.add_patch(obj,bm,plan,surface)
check('Both attached ends reuse manifold border vertices',
      all(len(bm.edges.get(edge).link_faces)==2 for edge in (start,end)) and len(bm.verts)==22)
state=flow.record(obj,vertices,faces,plan)
saved=[p.copy() for p in state['controls']]
check('Last-strip record stores independent editable control coordinates',
      all(p==q and p is not q for p,q in zip(state['controls'],plan['flow_controls'])))
new=[p.copy() for p in saved]
new[1].x+=.3
redraw=flow.bezier_plan(new,8,.3,surface,obj=obj,start=state['start'],end=state['end'],fixed_order=True)
anchors={v:v.co.copy() for v in state['anchors']}
flow.apply_redraw(obj,bm,state,redraw)
check('Bezier redraw preserves topology and both fixed border edges',
      len(bm.verts)==22 and len(bm.faces)==10 and all(v.co==p for v,p in anchors.items()))
check('Successful redraw updates its stored control shape',(state['controls'][1]-saved[1]).length>.2)
vertices[4][pin]=1
positions=[v.co.copy() for v in vertices]
saved=[p.copy() for p in state['controls']]
rejects('Pinned redraw fails safely',lambda: flow.apply_redraw(obj,bm,state,plan))
check('Failed redraw leaves vertices and recorded controls unchanged',
      all(v.co==p for v,p in zip(vertices,positions)) and all(p==q for p,q in zip(saved,state['controls'])))

bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.mesh.primitive_uv_sphere_add(segments=64,ring_count=32,radius=2)
sphere=bpy.context.active_object
curved=core.SourceSurface(sphere,bpy.context.evaluated_depsgraph_get())
controls=flow.default_controls((-.5,0,1.93),(.5,0,1.93))
controls[1]+=Vector((0,.3,3))
controls[2]+=Vector((0,.3,3))
plan=flow.bezier_plan(controls,12,.15,curved,.03)
obj,bm=target()
vertices,faces=core.add_patch(obj,bm,plan,curved)
check('Floating tangent handles project the curve and quads onto the sculpt',
      len(faces)==12 and all(abs((p-curved.nearest(p)[0]).length-.03)<.003 for p in plan['points']+plan['curve']))
check('Flow leaves Source geometry unchanged',[tuple(v.co) for v in source_obj.data.vertices]==source_before)
(ROOT/'.test-output/flow-bezier-core-results.json').write_text(json.dumps({'status':'passed','checks':results},indent=2),encoding='utf-8')
print('BEZIER CORE COMPLETE',len(results),flush=True)
betopo.unregister()
