"""Feature compilers: each takes a Build and stages files / plugin config for its part of the project."""
from . import text, textures, runtime, buildings, interiors, events, villagers, scripts

# order matters: buildings and interiors create variants that text/events then target
FEATURES = [
    ("buildings", buildings.compile),
    ("interiors", interiors.compile),
    ("villagers", villagers.compile),
    ("events", events.compile),         # adds the text of its messages for text to apply
    ("text", text.compile),
    ("textures", textures.compile),
    ("scripts", scripts.compile),
]
