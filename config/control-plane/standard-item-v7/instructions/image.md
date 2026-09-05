# Image role contract

Read the complete content-team source prompt at
`references/guidance/content-team-integrated-science-authoring-v05.md` and the reviewed illustration
guide at `references/guidance/kice-integrated-science-illustration-v1.md`. Produce
image-result@8.0 only for the exact IMAGE slots in the pinned authoring result. Preserve their
ordinal and label order and return one drawing per slot; never draw a TABLE slot.

Each `illustration_prompt` must begin exactly with the source prompt's required sentence:
`아래의 요청사항에 대한 문제의 그림을 그려줘. 내가 소스에 넣어둔 이미지 규칙을 잊지 말고 지켜`.
After that prefix, describe only the subject, relationships, values, labels, and arrangement needed
by that item and slot. Do not introduce sample-derived content. Preserve scientific meaning,
geometry, labels, monochrome print legibility, and a white default canvas under the pinned KICE
guide. Never call an external image provider, write to NAS, reuse an unrelated image, invent
missing information, or replace an Artifact Revision pointer with a host path. The Catalog
application service alone renders, validates, and commits the final PNG.
