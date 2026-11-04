"""Immutable native-reference vocabulary shared by producer and independent acceptance.

No XML parser, filesystem, allocator or merger implementation belongs here.
"""

from types import MappingProxyType

CATALOGS = frozenset(
    (
        "borderFills",
        "charProperties",
        "tabProperties",
        "numberings",
        "bullets",
        "paraProperties",
        "styles",
        "memoProperties",
    )
)
REFERENCES = MappingProxyType(
    {
        "borderfillidref": "borderFills",
        "charpridref": "charProperties",
        "parapridref": "paraProperties",
        "tabpridref": "tabProperties",
        "styleidref": "styles",
        "charstyleidref": "styles",
        "nextstyleidref": "styles",
        "outlineshapeidref": "numberings",
        "memoshapeidref": "memoProperties",
    }
)
FONT_LANGUAGES = MappingProxyType(
    {
        name.casefold(): name
        for name in ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
    }
)
ZERO_SENTINELS = frozenset(("borderFills", "numberings", "bullets", "memoProperties"))
OBJECTS = frozenset(
    (
        "tbl",
        "pic",
        "line",
        "rect",
        "ellipse",
        "arc",
        "polygon",
        "curve",
        "ole",
        "container",
        "equation",
        "video",
        "connectLine",
        "fieldBegin",
    )
)
