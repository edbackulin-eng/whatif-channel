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

# --- thumbnails -------------------------------------------------------------------
#
# A thumbnail is the one image that has to work at the size of a postage stamp
# against fifty others, and everything above is tuned for the opposite job. The
# preset for frames asks for restraint, distance and faces deliberately hidden;
# a thumbnail needs a lit human face in close up carrying one readable emotion,
# with the event behind it in full colour. So it gets its own preset, not a
# tweak of the one above, and nothing here is appended to a scene prompt.

THUMB_BASE = (
    "photorealistic photograph, 85mm portrait lens, face in sharp focus with "
    "visible skin texture and catchlights in the eyes, strong cinematic key light "
    "on the face and hard rim light from behind, bright punchy saturated colour, "
    "high contrast, high dynamic range, clean well exposed image"
)

# Written as things to avoid rather than as "no x" clauses for the defects that
# matter most: hands and faces are what the vision judge rejects candidates for,
# and the cheapest place to fix that is the prompt.
THUMB_NEGATIVE = (
    "no text, no letters, no words, no caption, no subtitle, no watermark, "
    "no logo, no signature, no border, no collage, no split screen, "
    "no hands, no fingers, no arms raised, "
    "no deformed face, no melted face, no asymmetric eyes, no extra eyes, "
    "no extra limbs, no extra heads, no plastic skin, no doll face, "
    "no cartoon, no anime, no illustration, no painting, no 3d render, "
    "no dark underexposed murky image, no blurry face, no motion blur"
)

# Hands are left out of every prompt on purpose. A six-fingered hand is the
# defect the judge rejects most often, and the foreground of a thumbnail does not
# need hands to carry a scream.
THUMB_FACES = (
    "extreme close up of a man's face filling the left half of the frame, mouth "
    "wide open screaming in terror, eyes wide, looking just past the camera, "
    "head and shoulders only",
    "extreme close up of an astronaut's face behind a raised helmet visor filling "
    "the left half of the frame, screaming in horror, eyes wide, the event "
    "reflected in the glass, looking just past the camera, head and shoulders only",
    "extreme close up of a woman's face filling the left half of the frame, frozen "
    "in shock, mouth open, eyebrows raised, eyes wide, looking just past the "
    "camera, head and shoulders only",
    "close up of an astronaut in a white spacesuit turned three quarters towards "
    "the left of the frame, helmet visor up, face lit, jaw dropped in disbelief, "
    "staring just past the camera, head and shoulders only",
    "extreme close up of a young man's face in the left third of the frame, eyes "
    "squeezed shut in horror, shouting, head tilted back, head and shoulders only",
    "extreme close up of a woman's face in the left half of the frame, terrified, "
    "mouth open mid scream, looking just off camera, head and shoulders only",
)


def thumbnail_prompt(event, index=0, centred=False):
    """One FLUX prompt for a thumbnail candidate: a face, then the event behind it.

    `index` picks the face, so a batch of candidates differs in more than its
    seed. `centred` is for a half of a split comparison, where the face has to
    sit in the middle of its own half rather than in the left of a full frame.
    """
    face = THUMB_FACES[index % len(THUMB_FACES)]
    if centred:
        face = (face.replace("filling the left half of the frame", "centred in the frame")
                    .replace("in the left third of the frame", "centred in the frame")
                    .replace("towards the left of the frame", "towards the camera"))
        behind = f"behind the figure, {event.strip().rstrip('.')}, filling the background"
    else:
        behind = (f"behind and to the right of the figure, {event.strip().rstrip('.')}, "
                  f"filling the right half of the frame")
    return ", ".join([face, behind, THUMB_BASE, THUMB_NEGATIVE])
