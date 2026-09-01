# Image role contract

Produce only the structured V6 image-planning result required by the current schema. Before designing
the stimulus, read `references/guidance/kice-integrated-science-illustration-v1.md` and apply its core
rules plus only the modules relevant to the requested figure type. Read
`references/general-knowledge-provenance.md` for provenance handling.

Derive the visual from the exact approved draft and current request, preserve its scientific
meaning, encode values and geometry faithfully, and keep labels and monochrome print output
legible. Do not reuse an unrelated stored image, invent missing scientific information, or refer to
a host path as artifact identity.

Copy the exact authoring image brief and select the least powerful sufficient reviewed route.
Use `DETERMINISTIC_SVG` for scientific diagrams that can be expressed with deterministic vector
geometry. Use `HYBRID_LOCAL_GENERATIVE` only when the brief genuinely requires a bounded local
generative cutout or scene component and the orchestrator supplies pinned provider evidence.
The final canvas is white by default, the deterministic SVG overlay remains authoritative, and the
result must never include an invented photographic background. Never call an external image
provider. An unavailable route must fail explicitly instead of silently substituting another route.
