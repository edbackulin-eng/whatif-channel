"""The channel's visual preset for generated frames.

The hard constraint: a FLUX frame and a NASA photograph sit four seconds apart in
the same cut. If the generated material looks like concept art while the archive
looks like photography, every seam shows. So the preset pushes FLUX toward
*camera* language, not illustration language:

  - photographic, not painted or rendered
  - light that has a physical source, mostly a single hard one
  - restrained saturation, because `core/grade.py` adds the channel's colour on
    top of every frame; a frame that arrives already graded ends up doubled
  - deep shadows that hold detail, matching how orbital photography falls off
  - wide, static framing - no dutch angles, no lens flares, no bokeh balls

Everything here is appended by the pipeline; a scene prompt describes only what is
visible in that shot.
"""

# What every generated frame gets.
BASE = (
    "photorealistic cinematic film still, shot on 35mm, natural volumetric light, "
    "single dominant light source, deep shadows with retained detail, "
    "restrained desaturated colour, cool blue-grey shadows and warm amber highlights, "
    "wide establishing composition, deep focus, fine film grain, high detail"
)

# What it must never contain.
NEGATIVE = (
    "no text, no letters, no captions, no watermark, no logo, no signature, "
    "no borders, no collage, no split screen, no cartoon, no anime, no illustration, "
    "no painting, no 3d render look, no oversaturated colour, no lens flare, "
    "no fisheye, no tilted horizon, no extra limbs, no deformed faces"
)

# People appear often (a channel about consequences needs human scale), but never
# as identifiable portraits: no real person is depicted, and faces invite the
# uncanny-valley failure that marks a video as AI-made.
PEOPLE = (
    "people seen as distant silhouettes or from behind, faces not visible, "
    "small in frame for scale"
)

ASPECT = {"width": 1360, "height": 768}      # 16:9, a size schnell handles well
STEPS = 4                                     # schnell is distilled to 4 steps
GUIDANCE = 0.0                                # and ignores CFG entirely


def scene_prompt(description, with_people=False):
    """Full prompt for one scene from a short visual description."""
    parts = [description.strip().rstrip(".")]
    if with_people:
        parts.append(PEOPLE)
    parts.append(BASE)
    parts.append(NEGATIVE)
    return ", ".join(parts)


# Ten probes chosen to stress the preset where it is most likely to break:
# ground-level human scale, water, night, interiors, scale against architecture,
# and the purely imaginary shots no archive can supply.
STYLE_TEST_SCENES = [
    ("an ordinary city street on a clear morning, an enormous moon low on the "
     "horizon between the buildings", True),
    ("a wide empty beach at low tide under a vast moon, wet sand reflecting the "
     "sky", True),
    ("a coastal motorway submerged under shallow seawater, road signs half "
     "covered, grey overcast light", False),
    ("the moon filling half the sky above a mountain range at dusk, deep cracks "
     "spreading across its surface", False),
    ("a harbour at night, water risen over the quay, street lamps reflecting on "
     "the flooded stone", True),
    ("the moon breaking apart into a ring of rock fragments seen from high above "
     "the earth's atmosphere", False),
    ("burning fragments of rock entering the atmosphere at night, seen from a "
     "field far from any city", False),
    ("a control room with banks of monitors, operators watching data, cold screen "
     "light on their backs", True),
    ("an abandoned coastal town covered in grey dust under a dim orange sky", False),
    ("the earth seen from deep space encircled by a dense ring of debris, "
     "sunlight catching the ring", False),
]

# Three thumbnail backgrounds. The channel's type block sits on the LEFT, so the
# subject must own the RIGHT of the frame - the flaw in the KT2 variant B frame
# was a dead black right half and a Moon too small to read at browse size.
THUMBNAIL_BACKGROUNDS = [
    ("an enormous cracked moon dominating the right side of the frame, looming "
     "low over a city skyline at dusk, glowing orange fissures across its "
     "surface, dust haze, dramatic rim light", False),
    ("a colossal moon filling the right half of the sky above a coastal city, "
     "surface splitting apart with molten light in the cracks, debris falling "
     "toward the horizon, turbulent clouds", False),
    ("a vast shattered moon hanging over a mountain valley on the right of frame, "
     "fragments breaking away trailing dust, low sun casting long shadows across "
     "the landscape", False),
]
