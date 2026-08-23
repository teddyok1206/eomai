import { createHash } from "node:crypto"
import { lstat, readFile, realpath, writeFile } from "node:fs/promises"
import { createRequire } from "node:module"
import path from "node:path"

const EXPECTED_VERSION = "4.9.0"
const ALLOWED_PRESETS = new Set([
  "official",
  "report",
  "plan",
  "notice",
  "minutes",
  "gaejosik",
  "press",
])

function digest(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`
}

function fail() {
  process.stderr.write("KORDOC_BRIDGE_FAILED\n")
  process.exitCode = 1
}

async function loadKordoc() {
  const nodeMajor = Number.parseInt(process.versions.node.split(".")[0], 10)
  if (!Number.isInteger(nodeMajor) || nodeMajor !== 22) throw new Error("node capability mismatch")
  const runtimeRoot = process.env.EOM_KORDOC_RUNTIME
  if (!runtimeRoot || !path.isAbsolute(runtimeRoot)) throw new Error("runtime unavailable")
  const root = await realpath(runtimeRoot)
  const manifest = path.join(root, "package.json")
  const require = createRequire(manifest)
  const kordoc = require("kordoc")
  if (kordoc.VERSION !== EXPECTED_VERSION) throw new Error("dependency mismatch")
  return kordoc
}

async function capabilities() {
  const kordoc = await loadKordoc()
  process.stdout.write(
    `${JSON.stringify({
      status: "READY",
      node_major: Number.parseInt(process.versions.node.split(".")[0], 10),
      kordoc_version: kordoc.VERSION,
      offline_required: true,
    })}\n`,
  )
}

async function render() {
  const workspace = await realpath(process.cwd())
  if (process.env.KORDOC_OFFLINE !== "1" || process.env.KORDOC_ROOT !== workspace) {
    throw new Error("offline boundary unavailable")
  }
  const preset = process.env.EOM_KORDOC_PRESET
  if (!preset || !ALLOWED_PRESETS.has(preset)) throw new Error("preset unsupported")

  const sourcePath = path.join(workspace, "input", "document.md")
  const outputPath = path.join(workspace, ".kordoc-generated.hwpx")
  const reportPath = path.join(workspace, ".kordoc-report.json")
  const sourceStat = await lstat(sourcePath)
  if (!sourceStat.isFile() || sourceStat.isSymbolicLink()) throw new Error("source unsafe")
  const markdown = await readFile(sourcePath, "utf8")

  const kordoc = await loadKordoc()
  const output = Buffer.from(await kordoc.markdownToHwpx(markdown, { gongmun: { preset } }))
  const validation = await kordoc.validateHwpx(output)
  const parsed = await kordoc.parseHwpx(output)
  const report = {
    schema_version: "1.0",
    kordoc_version: kordoc.VERSION,
    source_sha256: digest(Buffer.from(markdown, "utf8")),
    output_sha256: digest(output),
    validation_ok: validation.ok,
    validation_issue_count: validation.issues.length,
    parse_success: parsed.success,
    parsed_markdown_sha256: parsed.success ? digest(Buffer.from(parsed.markdown, "utf8")) : null,
    parse_warning_count: parsed.success ? (parsed.warnings?.length ?? 0) : 0,
    parsed_table_count: parsed.success
      ? parsed.blocks.filter((block) => block.type === "table").length
      : 0,
  }
  await writeFile(outputPath, output, { flag: "wx", mode: 0o600 })
  await writeFile(reportPath, `${JSON.stringify(report)}\n`, { flag: "wx", mode: 0o600 })
}

try {
  if (process.argv.length === 3 && process.argv[2] === "--capabilities") {
    await capabilities()
  } else if (process.argv.length === 2) {
    await render()
  } else {
    throw new Error("unsupported invocation")
  }
} catch {
  fail()
}
