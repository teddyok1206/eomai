# Image role contract

Produce only the structured V5 SVG-first stimulus result required by the current schema. Before designing the
stimulus, read `references/guidance/kice-integrated-science-illustration-v1.md` and apply its core
rules plus only the modules relevant to the requested figure type. Read
`references/general-knowledge-provenance.md` for provenance handling.

Derive the visual from the exact approved draft and current request, preserve its scientific
meaning, encode values and geometry faithfully, and keep labels and monochrome print output
legible. Do not reuse an unrelated stored image, invent missing scientific information, or refer to
a host path as artifact identity.

Copy the exact authoring image brief. Prefer DETERMINISTIC_SVG and return only the reviewed SVG
subset without a background; Catalog owns background composition and rasterization. Never call an
external image provider. A local-generative or human-reviewed route without its orchestrator-pinned
provider evidence must fail explicitly rather than fall back to invented pixels.
