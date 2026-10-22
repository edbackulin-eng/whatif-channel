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

# Never on a face. The first published batch had a red streak across the cheek
# of the man on 008 - read by the judge as fine and by a viewer as blood. The
# channel is about consequences, not injuries, and a wound on a thumbnail is
# what gets a video age-restricted or quietly not recommended.
THUMB_NO_GORE = (
    "no blood, no wounds, no cuts, no scratches, no bruises, no injuries, "
    "no red streaks or smears or drips on the skin, clean unmarked skin"
)

# On Earth nobody is wearing a spacesuit. Two of the first four Earth-bound
# thumbnails put an astronaut in front of a flooded coast and a collapsing city,
# which reads as "this video is about space" when it is not.
THUMB_NO_SUIT = "no spacesuit, no space helmet, no astronaut, no visor"

# --- the cast -----------------------------------------------------------------------
#
# One person per thumbnail, and not the same person every time: a feed of five
# videos with the same screaming man in the same helmet looks like one video
# uploaded five times. Each candidate is drawn from these, and thumbplan.py keeps
# the record of who appeared on the last five so the next one is someone else.
#
# Hands are left out of every prompt on purpose. A six-fingered hand is the
# defect the judge rejects most often, and the foreground of a thumbnail does not
# need hands to carry a scream.

CAST_GENDERS = ("woman", "man")
CAST_AGES = (24, 33, 42, 51, 58)          # 20-60, one per decade-ish
CAST_LOOKS = ("East Asian", "Black", "South Asian", "white", "Latina/Latino",
              "Middle Eastern")
CAST_ANGLES = (
    "three-quarter view, turned towards the event, looking just past the camera",
    "almost straight on, eyes fixed just past the lens",
    "slightly low angle looking up at the face, staring up and past the camera",
    "near profile, head turned towards the event, one eye catching the light",
    "slightly high angle looking down, face tilted up towards the sky",
)
CAST_EXPRESSIONS = (
    "screaming in terror, mouth wide open, eyes wide",
    "frozen in shock, jaw dropped, eyebrows raised, eyes wide",
    "horrified, mouth open, brow furrowed, eyes wide",
    "gasping in disbelief, mouth open, eyes wide",
)
# Ordinary clothes for ordinary people. Kept plain so none of them reads as a
# uniform or a costume.
CAST_CLOTHES = ("a grey hoodie", "a denim jacket", "a plain white t-shirt",
                "a dark wool coat", "a canvas work jacket", "a checked flannel shirt",
                "a knitted jumper", "a rain jacket")
# Where an Earth-bound story happens to the person, as the brief may name it.
CAST_PLACES = {
    "street": "standing in a city street",
    "coast": "standing on a coastline by the sea",
    "rooftop": "standing on a city rooftop",
    "home": "at the open window of their home",
    "field": "standing in an open field",
}


def age_band(age):
    """20s, 30s, 40s, 50s: what "the same type" means for age."""
    return f"{(int(age) // 10) * 10}s"


def person_type(person):
    """What counts as the same person for the no-repeat rule."""
    return (person.get("gender"), age_band(person.get("age", 0)), person.get("look"))


def describe_person(person, setting="earth", place="street", centred=False):
    """The foreground of a thumbnail prompt, from a cast entry."""
    noun = "woman" if person["gender"] == "woman" else "man"
    look = person["look"]
    if look == "Latina/Latino":
        look = "Latina" if noun == "woman" else "Latino"
    frame = ("centred in the frame" if centred
             else "filling the left half of the frame")
    if setting == "space":
        who = (f"extreme close up of a {person['age']}-year-old {look} {noun} "
               f"astronaut in a white spacesuit, helmet visor raised so the whole "
               f"face is clearly visible, {frame}")
    else:
        where = CAST_PLACES.get(place, CAST_PLACES["street"])
        who = (f"extreme close up of a {person['age']}-year-old {look} {noun} "
               f"wearing {person['clothes']}, {where}, {frame}")
    return ", ".join([who, person["expression"], person["angle"],
                      "head and shoulders only"])


def thumbnail_prompt(event, person, setting="earth", place="street", centred=False):
    """One FLUX prompt for a thumbnail candidate: a person, then the event behind.

    `setting` decides the costume and nothing else: a spacesuit only when the
    story happens in space, ordinary clothes and a real place everywhere else.
    `centred` is for a half of a split comparison, where the face sits in the
    middle of its own half rather than in the left of a full frame.
    """
    face = describe_person(person, setting, place, centred)
    event = event.strip().rstrip(".")
    if centred:
        behind = f"behind them, {event}, filling the background"
    else:
        behind = (f"behind and to the right of them, {event}, "
                  f"filling the right half of the frame")
    negative = [THUMB_NEGATIVE, THUMB_NO_GORE]
    if setting != "space":
        negative.append(THUMB_NO_SUIT)
    return ", ".join([face, behind, THUMB_BASE, *negative])
