# HWPX Template Bindings

`template-bindings.json` is compiled for exactly one reference package hash and one immutable
template revision. Reusing it with different template bytes is rejected.

## Locator Rules

Each binding records the field, package part, binding kind, expected original value, occurrence
count, namespace URI, local name, object ID when observed, and a bounded surrounding-structure
fingerprint. Text locators use observed text-node indexes and offsets, not namespace prefixes or an
absolute XPath. Binary bindings use the embedded reference PNG SHA-256. Equation bindings use only
an element or attribute observed by the importer.

## Marker Handling

The compiler concatenates `t` nodes inside one paragraph to locate a marker split by Hancom into
multiple runs. Exactly one logical occurrence is required. Replacement keeps prefix and suffix,
puts the replacement in the first bound text node, empties the consumed remainder, and records a
`SPLIT_MARKER_NORMALIZED` warning. The first run's style therefore remains authoritative.

Table bindings cover only the six pre-existing 2-by-3 cell markers. The renderer does not add or
remove rows, cells, or nested tables. A semantic extraction pass checks all six values afterward.

## Image And Equation

The reference image must be one embedded RGB/RGBA PNG identified by its exact hash. Output must be
an RGB/RGBA 800-by-500 PNG with the input contract hash. Only bytes at the existing binary path are
changed, preserving object and manifest relationships.

An equation marker must be unique in an observed equation text or attribute. If a Hancom version
does not preserve the marker, a unique `{{EOM_EQUATION_ANCHOR}}` and one nearby observed equation
source candidate in the same part are required. The renderer retains the equation object ID and
accepts only the bounded POC equation grammar. Manual Hancom validation remains authoritative for
visual rendering.
