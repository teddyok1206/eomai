const PREVIEW_BLOCK_TYPES = new Set(["paragraph", "table", "image", "equation", "statement_set"]);

export function orderedItemPreviewBlocks(preview) {
  if (!preview || preview.schema_version !== "2.0" || !Array.isArray(preview.blocks)) {
    throw new Error("ITEM_PREVIEW_CONTRACT_INVALID");
  }
  const identifiers = new Set();
  for (const block of preview.blocks) {
    if (!block || !PREVIEW_BLOCK_TYPES.has(block.type) || typeof block.block_id !== "string") {
      throw new Error("ITEM_PREVIEW_BLOCK_INVALID");
    }
    if (identifiers.has(block.block_id)) throw new Error("ITEM_PREVIEW_BLOCK_DUPLICATE");
    identifiers.add(block.block_id);
  }
  return [...preview.blocks];
}

export function formatEquationSource(source) {
  if (typeof source !== "string" || !source.length || source.length > 4000) {
    throw new Error("ITEM_PREVIEW_EQUATION_INVALID");
  }
  const superscript = {"0":"⁰", "1":"¹", "2":"²", "3":"³", "4":"⁴", "5":"⁵", "6":"⁶", "7":"⁷", "8":"⁸", "9":"⁹", "+":"⁺", "-":"⁻"};
  const subscript = {"0":"₀", "1":"₁", "2":"₂", "3":"₃", "4":"₄", "5":"₅", "6":"₆", "7":"₇", "8":"₈", "9":"₉", "+":"₊", "-":"₋"};
  const translate = (value, table) => [...value].map((character) => table[character] || character).join("");
  return source
    .replaceAll("\\times", "×").replaceAll(" times ", " × ")
    .replaceAll("\\cdot", "·").replaceAll(" cdot ", " · ")
    .replaceAll("\\leq", "≤").replaceAll(" leq ", " ≤ ")
    .replaceAll("\\geq", "≥").replaceAll(" geq ", " ≥ ")
    .replaceAll("\\neq", "≠").replaceAll(" neq ", " ≠ ")
    .replace(/\^\{?([+-]?[0-9]+)\}?/g, (_, value) => translate(value, superscript))
    .replace(/_\{?([+-]?[0-9]+)\}?/g, (_, value) => translate(value, subscript))
    .replace(/\\?sqrt\s*\{([^{}]+)\}/g, "√($1)")
    .replace(/\\?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}/g, "($1)⁄($2)");
}
