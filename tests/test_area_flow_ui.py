# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Actual mouse/key workflows for Area and Flow in an isolated Blender UI."""
import json
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if bpy.app.background or bpy.app.version[:2] != (5,1):
    raise RuntimeError('Use an isolated Blender 5.1 UI with --factory-startup --enable-event-simulate')
import betopo
from betopo import core,dock,tools

KEYCONFIG = Path(sys.argv[sys.argv.index('--keyconfig')+1]).expanduser().resolve(strict=True) if '--keyconfig' in sys.argv else None
MODE = 'custom' if KEYCONFIG else 'default'
OUTPUT = ROOT/'.test-output'/('area-flow-ui-'+MODE)
OUTPUT.mkdir(parents=True,exist_ok=True)
bpy.context.preferences.use_preferences_save = False
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.filepaths.use_auto_save_temporary_files = False
if KEYCONFIG:
    bpy.utils.keyconfig_set(str(KEYCONFIG))
betopo.register()
window = bpy.context.window_manager.windows[0]
results,drawn = [],set()
original_draw = betopo.VIEW3D_PT_betopo.draw


def record_draw(self,context):
    drawn.add(context.scene.betopo.tool)
    original_draw(self,context)


betopo.VIEW3D_PT_betopo.draw = record_draw


def area():
    return next(a for a in window.screen.areas if a.type == 'VIEW_3D')


def region():
    return next(r for r in area().regions if r.type == 'WINDOW')


def call(operator,*args,**kwargs):
    with bpy.context.temp_override(window=window,area=area(),region=region()):
        return operator(*args,**kwargs)


def layout():
    with bpy.context.temp_override(window=window,area=area(),region=region()):
        return dock.layout_for(bpy.context,area(),region())


def check(name,condition):
    assert condition,name
    results.append(name)
    print('AREA FLOW UI PASS',name,flush=True)


def at(x,y,name='MOUSEMOVE',value='NOTHING',**kwargs):
    window.event_simulate(type=name,value=value,x=int(x),y=int(y),**kwargs)
    yield


def world(co,name='MOUSEMOVE',value='NOTHING',**kwargs):
    r=region()
    p=view3d_utils.location_3d_to_region_2d(r,area().spaces.active.region_3d,Vector(co))
    assert p is not None
    yield from at(r.x+p.x,r.y+p.y,name,value,**kwargs)


def key(name,**kwargs):
    yield from world((0,0,0),name,'PRESS',**kwargs)
    yield from world((0,0,0),name,'RELEASE',**kwargs)
    yield; yield


def click_button(identifier):
    button=next(b for b in layout()['buttons'] if b['id']==identifier)
    x,y,w,h=button['rect']
    x,y=region().x+x+w/2,region().y+y+h/2
    yield from at(x,y)
    yield from at(x,y,'LEFTMOUSE','PRESS')
    yield from at(x,y,'LEFTMOUSE','RELEASE')
    yield; yield


def stroke(points,**kwargs):
    yield from world(points[0])
    yield from world(points[0],'LEFTMOUSE','PRESS',**kwargs)
    for point in points[1:]:
        yield from world(point,**kwargs)
    yield from world(points[-1],'LEFTMOUSE','RELEASE',**kwargs)
    yield; yield


def bm():
    return bmesh.from_edit_mesh(bpy.context.scene.betopo.target.data)


def counts():
    mesh=bm()
    return len(mesh.verts),len(mesh.edges),len(mesh.faces)


def suite():
    call(bpy.ops.mesh.primitive_plane_add,size=100)
    source=bpy.context.active_object
    original=[tuple(v.co) for v in source.data.vertices]
    call(bpy.ops.betopo.setup)
    yield; yield; yield
    rv=area().spaces.active.region_3d
    rv.view_rotation=Quaternion((1,0,0,0))
    rv.view_location=Vector((0,0,0))
    rv.view_distance=9
    rv.view_perspective='ORTHO'
    settings=bpy.context.scene.betopo
    settings.area_quad_size=.5
    settings.flow_width=.2
    settings.flow_segments=8
    settings.weld_distance=.00001
    yield; yield; yield
    check('Area and Flow appear alongside the original Draw',
          {'AREA','FLOW','DRAW'} <= {b['id'] for b in layout()['buttons']})
    yield from click_button('AREA')
    corners=[Vector(p) for p in ((-2,-1,0),(1,-1,0),(1,1,0),(-2,1,0))]
    for i in range(4):
        a,b=corners[i],corners[(i+1)%4]
        yield from stroke([a,a.lerp(b,.5),b])
        check('Area side '+str(i+1)+' remains uncommitted',counts()==(0,0,0) and len(tools.SESSION._area_guides)==i+1)
    check('Four sides produce a quad-grid preview',tools.SESSION._plan is not None and len(tools.SESSION._plan['faces'])>=24)
    old_faces=len(tools.SESSION._plan['faces'])
    settings.area_quad_size=.25
    yield; yield; yield
    check('Area Quad Size changes preview density live',len(tools.SESSION._plan['faces'])>old_faces and counts()==(0,0,0))
    settings.area_columns,settings.area_rows=3,2
    yield; yield; yield
    check('Area manual subdivisions update the preview',len(tools.SESSION._plan['faces'])==6)
    first=tools.SESSION._area_guides[0]['points'][0].copy()
    moved=first+Vector((-.2,-.2,0))
    yield from stroke([first,moved],ctrl=True)
    check('Ctrl-drag reshapes the Area corner without building geometry',
          (tools.SESSION._area_guides[0]['points'][0]-moved).length<.03 and counts()==(0,0,0) and tools.SESSION._plan is not None)
    before=tools.SESSION._area_guides[0]['points'][0].copy()
    yield from world(before,'LEFTMOUSE','PRESS',ctrl=True)
    yield from world(before+Vector((-.2,0,0)),ctrl=True)
    yield from key('ESC')
    check('Esc during corner drag restores the previous preview',
          (tools.SESSION._area_guides[0]['points'][0]-before).length<1e-6 and tools.SESSION._plan is not None)
    yield from stroke([before,tools.SESSION._area_guides[2]['points'][0].copy()],ctrl=True)
    check('Releasing a folded Area corner preserves the session and mesh',
          tools.SESSION is not None and not tools.SESSION._drawing and tools.SESSION._plan is None and counts()==(0,0,0))
    yield from key('ESC')
    for i in range(4):
        yield from stroke([corners[i],corners[(i+1)%4]])
    check('Area recovers after discarding an invalid corner preview',tools.SESSION._plan is not None and counts()==(0,0,0))
    yield from key('BACK_SPACE')
    check('Backspace removes only the last guide side',len(tools.SESSION._area_guides)==3 and tools.SESSION._plan is None)
    a=tools.SESSION._area_guides[-1]['points'][-1].copy()
    b=tools.SESSION._area_guides[0]['points'][0].copy()
    yield from stroke([a,a.lerp(b,.5),b])
    call(bpy.ops.screen.screenshot,filepath=str(OUTPUT/'area-preview.png'))
    yield from key('RET')
    check('Enter commits the Area grid once',len(bm().faces)==6 and not tools.SESSION._area_guides)
    yield from key('Z',ctrl=True)
    check('Native Undo removes the Area grid',counts()==(0,0,0) and tools.SESSION is None)
    yield from click_button('AREA')
    for i in range(4):
        yield from stroke([corners[i],corners[(i+1)%4]])
    yield from key('RET')
    check('Area can build again after native Undo',len(bm().faces)==6)
    bottom=min((e for e in bm().edges if e.is_boundary),key=lambda e: sum(v.co.y for v in e.verts))
    midpoint=sum((settings.target.matrix_world@v.co for v in bottom.verts),Vector())*.5
    yield from world(midpoint,'LEFTMOUSE','PRESS')
    yield from world(midpoint,'LEFTMOUSE','RELEASE')
    yield; yield
    check('Clicking a border reuses it as an Area side',len(tools.SESSION._area_guides)==1 and tools.SESSION._area_guides[0].get('existing'))
    a,b=[p.copy() for p in tools.SESSION._area_guides[0]['points']]
    outside=Vector((0,-1,0))
    for p,q in ((b,b+outside),(b+outside,a+outside),(a+outside,a)):
        yield from stroke([p,q])
    check('Attached Area locks the boundary subdivision count',tools.SESSION._plan['grid_columns']==1)
    yield from key('RET')
    check('Attached Area shares a manifold boundary edge',len(bottom.link_faces)==2 and len(bm().faces)==8)
    yield from click_button('FLOW')
    yield from stroke([(2,-1,0),(2.25,0,0),(2,1,0)])
    check('Flow previews a strip without changing mesh',tools.SESSION._plan is not None and len(tools.SESSION._plan['faces'])==8 and len(bm().faces)==8)
    session=tools.SESSION
    check('Flow uses only two endpoints and two handles, ignoring freehand detours',
          len(session._flow_controls)==4 and not session._stroke and all(abs(p.x-2)<.03 for p in session._plan['curve']))
    before=[p.copy() for p in session._flow_controls]
    yield from stroke([before[1],before[1]+Vector((.5,0,0))])
    check('Dragging a tangent handle bends the preview without creating mesh',
          session._plan is not None and max(p.x for p in session._plan['curve'])>2.15 and len(bm().faces)==8)
    check('A tangent drag leaves the two endpoints and opposite handle fixed',
          all((session._flow_controls[i]-before[i]).length<1e-6 for i in (0,2,3)))
    before=[p.copy() for p in session._flow_controls]
    yield from stroke([before[3],before[3]+Vector((.2,0,0))])
    check('Dragging an endpoint moves its own handle with it',
          ((session._flow_controls[2]-session._flow_controls[3])-(before[2]-before[3])).length<1e-6 and
          (session._flow_controls[3]-before[3]).length>.1)
    before=[p.copy() for p in session._flow_controls]
    yield from world(before[2],'LEFTMOUSE','PRESS')
    yield from world(before[2]+Vector((-.3,0,0)))
    yield from key('ESC')
    yield from world(before[2],'LEFTMOUSE','RELEASE')
    check('Esc during a tangent drag restores the entire previous preview',
          session._plan is not None and all((p-q).length<1e-6 for p,q in zip(session._flow_controls,before)))
    before=[p.copy() for p in session._flow_controls]
    middle=session._plan['curve'][len(session._plan['curve'])//2].copy()
    yield from stroke([middle,middle+Vector((.25,0,0))])
    deltas=[p-q for p,q in zip(session._flow_controls,before)]
    check('Dragging the white curve translates all controls together',
          deltas[0].length>.15 and all((d-deltas[0]).length<1e-4 for d in deltas) and len(bm().faces)==8)
    handle=session._flow_controls[1].copy()
    yield from world(handle,'LEFTMOUSE','PRESS')
    yield from world(handle+Vector((.1,0,0)))
    yield from at(region().x+region().width-5,region().y+region().height/2,'LEFTMOUSE','RELEASE')
    check('Release over Sidebar finishes a Flow drag without getting stuck',
          session._flow_drag is None and not session._drawing and session._plan is not None)
    yield from key('ESC')
    yield from world((2,-1,0),'LEFTMOUSE','PRESS')
    yield from world((2,-1,0),'LEFTMOUSE','RELEASE')
    check('The first click leaves one visible endpoint and no geometry',len(session._flow_controls)==1 and session._plan is None)
    yield from world((2,1,0),'LEFTMOUSE','PRESS')
    yield from world((2,1,0),'LEFTMOUSE','RELEASE')
    check('The second click creates a two-endpoint Bezier preview',len(session._flow_controls)==4 and session._plan is not None)
    before=[p.copy() for p in session._flow_controls]
    yield from world((3,1,0),'LEFTMOUSE','PRESS')
    yield from world((3,1,0),'LEFTMOUSE','RELEASE')
    check('Extra clicks do not append points or discard the preview',all((p-q).length<1e-6 for p,q in zip(session._flow_controls,before)))
    settings.flow_segments=12
    settings.flow_width=.35
    settings.offset=.04
    yield; yield; yield
    check('Flow segments, width and offset update the preview live',
          len(session._plan['faces'])==12 and len(bm().faces)==8 and all(abs(p.z-.04)<1e-5 for p in session._plan['points']))
    settings.offset=0
    yield; yield
    handle=session._flow_controls[1].copy()
    yield from stroke([handle,handle+Vector((.4,0,0))])
    call(bpy.ops.screen.screenshot,filepath=str(OUTPUT/'flow-preview.png'))
    yield from key('RET')
    check('Flow Enter creates a reusable last-strip record',len(bm().faces)==20 and tools.SESSION._flow_last is not None)
    last=tools.SESSION._flow_last
    positions=[v.co.copy() for v in last['vertices']]
    before_counts=counts()
    settings.flow_mode='REDRAW'
    yield; yield; yield
    check('Redraw Last restores editable endpoints and tangent handles',
          len(session._flow_controls)==4 and session._plan is not None and
          all((p-q).length<1e-6 for p,q in zip(session._flow_controls,last['controls'])))
    handle=session._flow_controls[1].copy()
    yield from stroke([handle,handle+Vector((-.7,0,0))])
    check('Flow redraw previews without moving existing vertices',all((v.co-p).length<1e-7 for v,p in zip(last['vertices'],positions)))
    yield from key('RET')
    check('Flow redraw changes path while preserving topology',counts()==before_counts and any((v.co-p).length>.05 for v,p in zip(last['vertices'],positions)))
    settings.flow_mode='NEW'
    settings.flow_segments=6
    yield; yield; yield
    end=last['vertices'][-2:]
    midpoint=sum((settings.target.matrix_world@v.co for v in end),Vector())*.5
    yield from stroke([midpoint,midpoint+Vector((0,-.5,0))])
    check('Flow rejects drawing inward over its existing strip',tools.SESSION._plan is None and len(bm().faces)==20)
    yield from key('ESC')
    yield from stroke([midpoint,midpoint+Vector((0,.5,0)),midpoint+Vector((0,1,0))])
    check('Flow detects the existing end border',set(tools.SESSION._plan['existing'].values())==set(end))
    fixed=session._flow_controls[0].copy()
    yield from stroke([fixed,fixed+Vector((.3,0,0))])
    check('Attached endpoints cannot accidentally move existing border vertices',
          (session._flow_controls[0]-fixed).length<1e-6 and len(bm().faces)==20)
    yield from key('RET')
    check('Flow extension welds onto the strip without duplicate vertices',len(bm().edges.get(end).link_faces)==2 and len(bm().faces)==26)
    yield from key('Z',ctrl=True)
    check('Native Undo removes the Flow extension',len(bm().faces)==20 and tools.SESSION is None)
    yield from click_button('DRAW')
    yield from stroke([(-3,2,0),(-2,2.3,0),(-1,2,0)])
    check('Original Draw still previews its own strip',tools.SESSION._tool=='DRAW' and tools.SESSION._plan is not None)
    yield from key('ESC')
    check('Cancelling Draw preserves both new tools meshes',len(bm().faces)==20)
    check('Native Sidebar renders the new tool parameters',{'AREA','FLOW'}<=drawn)
    check('Source geometry is unchanged',original==[tuple(v.co) for v in source.data.vertices])
    betopo.unregister()
    check('Cleanup removes all modal controllers and sessions',not dock.CONTROLLERS and tools.SESSION is None)


runner=suite()


def tick():
    try:
        next(runner)
        return .10
    except StopIteration:
        status,error='passed',None
    except Exception:
        status,error='failed',traceback.format_exc()
        print(error,flush=True)
        call(bpy.ops.screen.screenshot,filepath=str(OUTPUT/'failure.png'))
    (OUTPUT/'results.json').write_text(json.dumps({'status':status,'mode':MODE,'tests':results,'error':error},indent=2),encoding='utf-8')
    print('AREA FLOW UI COMPLETE',MODE,status,len(results),flush=True)
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(tick,first_interval=3)
