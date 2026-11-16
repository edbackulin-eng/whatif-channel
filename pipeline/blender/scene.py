"""One 3D shot, rendered inside Blender (owner 15.11: Earth with NASA Blue/Black Marble, the Sun, the Moon,
an asteroid, orbits, a wave over the ocean - with a moving camera).

    blender -b -noaudio -P pipeline/blender/scene.py -- '{"template": "earth_moon", "seconds": 5, "out": "x.mp4", ...}'

Templates: earth_day, earth_night, earth_moon, moon_rise, sun, asteroid, orbits, ocean, ocean_moon.
Every shot carries a seed: the start rotation, the camera's path and the light change with it, so no two
3D shots of a film are the same. Cycles on the CPU, denoised; textures from assets/textures (NASA, public
domain): blue_marble.jpg, black_marble.jpg, moon.jpg - a plain shader stands in for a missing one.
"""
import json
import math
import os
import random
import sys

import bpy

ARGS = json.loads(sys.argv[sys.argv.index("--") + 1])
TEX = ARGS.get("textures") or os.path.join(os.path.dirname(__file__), "..", "..", "assets", "textures")
RNG = random.Random(int(ARGS.get("seed", 1)))
FPS = int(ARGS.get("fps", 24))


def tex(name):
    p = os.path.abspath(os.path.join(TEX, name))
    return p if os.path.exists(p) else None


# ------------------------------------------------------------------ setup
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = int(ARGS.get("samples", 16))
sc.cycles.use_denoising = True
try:
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception:                                                       # noqa: BLE001
    pass
# 16.11: the first test took 30-37 s a frame; a space scene needs one bounce, no caustics, and the scene
# kept in memory between frames
sc.cycles.max_bounces = 2
for attr, v in (("diffuse_bounces", 1), ("glossy_bounces", 1), ("transmission_bounces", 0),
                ("transparent_max_bounces", 2), ("volume_bounces", 0), ("caustics_reflective", False),
                ("caustics_refractive", False), ("use_adaptive_sampling", True), ("adaptive_threshold", 0.05)):
    try:
        setattr(sc.cycles, attr, v)
    except Exception:                                                   # noqa: BLE001
        pass
try:
    sc.cycles.denoising_prefilter = "FAST"
except Exception:                                                       # noqa: BLE001
    pass
sc.render.use_persistent_data = True
sc.render.resolution_x, sc.render.resolution_y = int(ARGS.get("w", 1280)), int(ARGS.get("h", 720))
sc.render.fps = FPS
N = max(2, int(round(float(ARGS["seconds"]) * FPS)))
sc.frame_start, sc.frame_end = 1, N
sc.render.image_settings.file_format = "FFMPEG"
sc.render.ffmpeg.format = "MPEG4"
sc.render.ffmpeg.codec = "H264"
sc.render.ffmpeg.constant_rate_factor = "HIGH"
sc.render.filepath = ARGS["out"]
sc.view_settings.view_transform = "Filmic" if "Filmic" in [x.identifier for x in
                                                          sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "AgX"


def world_stars(strength=1.0):
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    stars = tex("stars.png")                       # a ready star field (tools/v2_assets.py): a lookup, not a Voronoi
    if stars:
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(stars)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    else:
        bg.inputs["Color"].default_value = (0, 0, 0, 1)
    bg.inputs["Strength"].default_value = 0.8 * strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def sky_world(sun_elev=8.0, strength=0.8):
    w = bpy.data.worlds.new("sky")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "NISHITA"
        sky.sun_elevation = math.radians(sun_elev)
        sky.sun_rotation = math.radians(RNG.uniform(0, 360))
    except Exception:                                                   # noqa: BLE001
        pass
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def sun_lamp(direction=(-1.0, 0.4, 0.3), strength=4.0):
    d = bpy.data.lights.new("sun", "SUN")
    d.energy = strength
    o = bpy.data.objects.new("sun", d)
    sc.collection.objects.link(o)
    v = direction
    # the lamp shines along its local -Z: tilt by theta about X, turn by phi about Z so that -Z becomes v
    # (16.11: the old phi mirrored x and y - the Moon and the Earth were lit from behind)
    o.rotation_euler = (math.atan2(math.hypot(v[0], v[1]), -v[2]), 0, math.atan2(-v[0], v[1]))
    return v


def sphere(name, radius, loc=(0, 0, 0), seg=128):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=seg // 2, radius=radius, location=loc)
    o = bpy.context.object
    o.name = name
    bpy.ops.object.shade_smooth()
    return o


def mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree


def earth(radius=1.0, sun_dir=(-1.0, 0.4, 0.3), night_boost=1.0):
    o = sphere("earth", radius)
    m, nt = mat("earth")
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.65
    day = tex("blue_marble.jpg")
    if day:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(day)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (0.05, 0.15, 0.45, 1)
    night = tex("black_marble.jpg")
    if night:
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(night)
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        dot = nt.nodes.new("ShaderNodeVectorMath")
        dot.operation = "DOT_PRODUCT"
        dot.inputs[1].default_value = tuple(-x for x in sun_dir)
        nt.links.new(geo.outputs["Normal"], dot.inputs[0])
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value = -0.15
        rng.inputs["From Max"].default_value = 0.2
        rng.inputs["To Min"].default_value = 0.0
        rng.inputs["To Max"].default_value = 3.0 * night_boost
        nt.links.new(dot.outputs["Value"], rng.inputs["Value"])
        key = "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
        nt.links.new(n.outputs["Color"], bsdf.inputs[key])
        nt.links.new(rng.outputs["Result"], bsdf.inputs["Emission Strength"])
    # the atmosphere: a blue glow at the rim, in the planet's own shader (16.11: a transparent shell around
    # it cost most of the 30 s a frame)
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.35
    pw = nt.nodes.new("ShaderNodeMath")
    pw.operation = "POWER"
    pw.inputs[1].default_value = 3.0
    nt.links.new(lw.outputs["Facing"], pw.inputs[0])
    rim = nt.nodes.new("ShaderNodeEmission")
    rim.inputs["Color"].default_value = (0.3, 0.6, 1.0, 1)
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 2.2
    nt.links.new(pw.outputs["Value"], mul.inputs[0])
    nt.links.new(mul.outputs["Value"], rim.inputs["Strength"])
    add = nt.nodes.new("ShaderNodeAddShader")
    outn = nt.nodes["Material Output"]
    nt.links.new(bsdf.outputs["BSDF"], add.inputs[0])
    nt.links.new(rim.outputs["Emission"], add.inputs[1])
    nt.links.new(add.outputs["Shader"], outn.inputs["Surface"])
    o.data.materials.append(m)
    o.rotation_euler = (math.radians(RNG.uniform(-10, 25)), 0, math.radians(RNG.uniform(0, 360)))
    spin = math.radians(RNG.uniform(8, 18)) * float(ARGS["seconds"]) / 5
    o.keyframe_insert("rotation_euler", frame=1)
    o.rotation_euler[2] += spin
    o.keyframe_insert("rotation_euler", frame=N)
    return o


def moon(radius, loc):
    o = sphere("moon", radius, loc, seg=96)
    m, nt = mat("moon")
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.95
    t = tex("moon.jpg")
    if t:
        ti = nt.nodes.new("ShaderNodeTexImage")
        ti.image = bpy.data.images.load(t)
        nt.links.new(ti.outputs["Color"], bsdf.inputs["Base Color"])
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.3
        nt.links.new(ti.outputs["Color"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    else:
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 18
        nt.links.new(noise.outputs["Fac"], bsdf.inputs["Base Color"])
    o.data.materials.append(m)
    o.rotation_euler[2] = math.radians(RNG.uniform(0, 360))
    return o


def emissive(name, radius, loc, color, strength):
    o = sphere(name, radius, loc, seg=64)
    m, nt = mat(name)
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color
    em.inputs["Strength"].default_value = strength
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 30
    mixc = nt.nodes.new("ShaderNodeMixRGB")
    mixc.inputs["Color1"].default_value = color
    mixc.inputs["Color2"].default_value = (1.0, 0.95, 0.6, 1)
    nt.links.new(noise.outputs["Fac"], mixc.inputs["Fac"])
    nt.links.new(mixc.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], nt.nodes["Material Output"].inputs["Surface"])
    o.data.materials.append(m)
    return o


def glare():
    sc.use_nodes = True
    nt = sc.node_tree
    rl = nt.nodes.get("Render Layers") or nt.nodes.new("CompositorNodeRLayers")
    comp = nt.nodes.get("Composite") or nt.nodes.new("CompositorNodeComposite")
    g = nt.nodes.new("CompositorNodeGlare")
    g.glare_type = "FOG_GLOW"
    g.threshold = 0.8
    g.size = 8
    nt.links.new(rl.outputs["Image"], g.inputs["Image"])
    nt.links.new(g.outputs["Image"], comp.inputs["Image"])


def camera(p0, p1, target=(0, 0, 0), lens=50):
    cd = bpy.data.cameras.new("cam")
    cd.lens = lens
    cd.clip_end = 5000
    c = bpy.data.objects.new("cam", cd)
    sc.collection.objects.link(c)
    sc.camera = c
    tgt = bpy.data.objects.new("tgt", None)
    sc.collection.objects.link(tgt)
    tgt.location = target
    tc = c.constraints.new("TRACK_TO")
    tc.target = tgt
    tc.track_axis = "TRACK_NEGATIVE_Z"
    tc.up_axis = "UP_Y"
    c.location = p0
    c.keyframe_insert("location", frame=1)
    c.location = p1
    c.keyframe_insert("location", frame=N)
    for fc in (c.animation_data.action.fcurves if c.animation_data and c.animation_data.action else []):
        for k in fc.keyframe_points:
            k.interpolation = "BEZIER"
    return c, tgt


def orbit_point(r, az, el):
    return (r * math.cos(el) * math.cos(az), r * math.cos(el) * math.sin(az), r * math.sin(el))


# ------------------------------------------------------------------ templates
T = ARGS["template"]
az = math.radians(RNG.uniform(0, 360))
el = math.radians(RNG.uniform(5, 25))
if T in ("earth_day", "earth_night"):
    world_stars()
    cdir = orbit_point(1.0, az, el)
    side = orbit_point(1.0, az + math.radians(90), 0)
    if T == "earth_day":      # light from behind the camera, a little to the side: the day side faces us
        sd = tuple(-0.85 * cdir[i] + 0.45 * side[i] for i in range(3))
    else:                     # light from beyond the Earth: the night side, its city lights, a bright rim
        sd = tuple(0.8 * cdir[i] + 0.55 * side[i] for i in range(3))
    sun_lamp(sd, 4.0 if T == "earth_day" else 2.5)
    earth(sun_dir=sd, night_boost=1.4 if T == "earth_night" else 1.0)
    r0, r1 = RNG.uniform(3.4, 4.2), RNG.uniform(2.6, 3.2)
    camera(orbit_point(r0, az, el), orbit_point(r1, az + math.radians(12), el))
elif T in ("earth_moon", "moon_rise"):
    world_stars()
    close = float(ARGS.get("moon_closeness", 1.0))            # 2 = twice as close
    d = 8.0 / close
    u = (math.cos(az), math.sin(az), 0.0)                     # Earth -> Moon
    p = (-math.sin(az), math.cos(az), 0.0)                    # sideways, where the camera stands
    if T == "earth_moon":
        # both bodies in the frame, side by side, lit from the camera's side (16.11: the Moon hid the Earth)
        sd = (-0.75 * p[0] + 0.35 * u[0], -0.75 * p[1] + 0.35 * u[1], -0.25)
        sun_lamp(sd, 4.5)
        earth(sun_dir=sd)
        ml = tuple(x * d for x in u)
        moon(0.27 * max(1.0, close ** 0.35), ml)
        mid = tuple(x * 0.5 for x in ml)
        c0 = tuple(mid[i] + p[i] * d * 1.35 + (0, 0, d * 0.22)[i] for i in range(3))
        c1 = tuple(mid[i] + p[i] * d * 1.18 + (0, 0, d * 0.16)[i] + u[i] * d * 0.05 for i in range(3))
        camera(c0, c1, target=mid, lens=35)
    else:
        # just above the Earth's limb, looking along the horizon, the Moon big and lit above it
        q, t = u, p                                           # radial (local "up") and along the horizon
        cam = tuple(x * 1.04 for x in q)
        dn = math.radians(-8)
        aim = tuple(t[i] * math.cos(dn) + q[i] * math.sin(dn) for i in range(3))
        me = math.radians(-6)
        mdir = tuple(t[i] * math.cos(me) + q[i] * math.sin(me) for i in range(3))
        D = d * 0.9
        ml = tuple(cam[i] + mdir[i] * D for i in range(3))
        sd = tuple(0.85 * t[i] - 0.4 * q[i] for i in range(3))   # the light travels from behind the camera
        sun_lamp(sd, 4.5)
        earth(sun_dir=sd)
        moon(0.27 * max(1.0, close ** 0.35), ml)
        c1 = tuple(x * 1.046 for x in q)
        camera(cam, tuple(c1[i] + t[i] * 0.01 for i in range(3)),
               target=tuple(cam[i] + aim[i] * 5 for i in range(3)), lens=35)
elif T == "sun":
    world_stars(0.5)
    emissive("sun", 1.0, (0, 0, 0), (1.0, 0.55, 0.12, 1), 25.0)
    glare()
    camera(orbit_point(5.5, az, el), orbit_point(4.5, az + math.radians(8), el), lens=45)
elif T == "asteroid":
    world_stars()
    cdir = orbit_point(1.0, az - math.radians(10), el)
    side = orbit_point(1.0, az + math.radians(80), 0)
    sd = tuple(-0.8 * cdir[i] + 0.5 * side[i] for i in range(3))
    sun_lamp(sd, 4.0)
    earth(sun_dir=sd)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=0.18)
    ast = bpy.context.object
    tx = bpy.data.textures.new("rock", "CLOUDS")
    tx.noise_scale = 0.35
    dm = ast.modifiers.new("disp", "DISPLACE")
    dm.texture = tx
    dm.strength = 0.08
    am, ant = mat("rock")
    ant.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.15, 0.12, 1)
    ant.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
    ast.data.materials.append(am)
    start = orbit_point(6.0, az + math.radians(40), math.radians(10))
    end = orbit_point(1.6, az + math.radians(10), math.radians(3))
    ast.location = start
    ast.keyframe_insert("location", frame=1)
    ast.location = end
    ast.keyframe_insert("location", frame=N)
    camera(orbit_point(4.6, az - math.radians(10), el), orbit_point(4.0, az, el), target=(0, 0, 0), lens=40)
elif T == "orbits":
    world_stars()
    emissive("sun", 0.6, (0, 0, 0), (1.0, 0.6, 0.15, 1), 20.0)
    glare()
    for r, col in ((4.0, (0.3, 0.7, 1.0, 1)), (6.5, (0.9, 0.5, 0.3, 1))):
        bpy.ops.curve.primitive_bezier_circle_add(radius=r)
        cv = bpy.context.object
        cv.data.bevel_depth = 0.012
        cm, cnt = mat(f"orbit{r}")
        cnt.nodes.remove(cnt.nodes["Principled BSDF"])
        e = cnt.nodes.new("ShaderNodeEmission")
        e.inputs["Color"].default_value = col
        e.inputs["Strength"].default_value = 3
        cnt.links.new(e.outputs["Emission"], cnt.nodes["Material Output"].inputs["Surface"])
        cv.data.materials.append(cm)
    pl = sphere("planet", 0.18, orbit_point(4.0, az, 0), seg=48)
    pm, pnt = mat("planet")
    pnt.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.1, 0.3, 0.8, 1)
    pl.data.materials.append(pm)
    pl.keyframe_insert("location", frame=1)
    pl.location = orbit_point(4.0, az + math.radians(25), 0)
    pl.keyframe_insert("location", frame=N)
    l = bpy.data.lights.new("p", "POINT")
    l.energy = 3000
    lo = bpy.data.objects.new("p", l)
    sc.collection.objects.link(lo)
    camera(orbit_point(11, az + 1.2, math.radians(38)), orbit_point(10, az + 1.35, math.radians(32)), lens=35)
elif T in ("ocean", "ocean_moon"):
    sky_world(sun_elev=RNG.uniform(-2, 6) if T == "ocean_moon" else RNG.uniform(4, 15),
              strength=0.35 if T == "ocean_moon" else 0.9)
    bpy.ops.mesh.primitive_plane_add(size=2)
    sea = bpy.context.object
    oc = sea.modifiers.new("ocean", "OCEAN")
    oc.resolution = 10
    oc.spatial_size = 60
    oc.wave_scale = float(ARGS.get("wave_scale", 2.0))
    oc.choppiness = 1.2
    oc.repeat_x = oc.repeat_y = 3
    oc.time = 1.0
    oc.keyframe_insert("time", frame=1)
    oc.time = 1.0 + float(ARGS["seconds"]) * 0.9
    oc.keyframe_insert("time", frame=N)
    sm, snt = mat("sea")
    b = snt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.01, 0.06, 0.1, 1)
    b.inputs["Roughness"].default_value = 0.08
    sea.data.materials.append(sm)
    sun_lamp((-0.6, 0.2, -0.25), 2.0 if T == "ocean_moon" else 4.0)
    if T == "ocean_moon":
        size = 6.0 * float(ARGS.get("moon_closeness", 2.0))
        mo = moon(size, (0, 260, 30 + size * 0.6))
        sun_lamp((0.0, 1.0, -0.3), 1.5)                  # light travelling away from the camera: the Moon's face lit
    camera((0, -20, 4.5), (0, -8, 3.5), target=(0, 120, 12), lens=24)
else:
    raise SystemExit(f"unknown template {T}")

bpy.ops.render.render(animation=True)
print("RENDERED", ARGS["out"])
