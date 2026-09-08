# Image role contract

Read the complete byte-pinned content-team source prompt and reviewed KICE illustration guide. Return
image-result@9.0 only for the exact ordered IMAGE slots in authoring-result@9.0; never draw a TABLE
slot or add sample-derived content.

For DETERMINISTIC_SVG, use the same safe compositor grammar enforced at result acceptance: an
optional exact 800 by 500 SVG root; only `g`, `rect`, `circle`, `ellipse`, `line`, `polyline`,
`polygon`, `path`, and `text`; bounded numeric coordinates, approved flat colors, and approved
fixed fonts. Do not emit `style`, `script`, `foreignObject`, `image`, external or data references,
`url()`, gradients or paint servers, filters, or masks. Preserve every required label. The Catalog
application service alone validates, rasterizes, and commits the resulting artifact.
