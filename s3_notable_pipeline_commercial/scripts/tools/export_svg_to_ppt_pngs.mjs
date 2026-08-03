#!/usr/bin/env node
/**
 * Export Mermaid diagrams to PowerPoint-friendly PNGs (labels render via Chromium).
 *
 * Run from s3_notable_pipeline (npm install includes @mermaid-js/mermaid-cli).
 * Also requires: pip install pillow
 *
 * Fig01 uses the sibling .mmd source and produces two vertical slide crops:
 *   node scripts/tools/export_svg_to_ppt_pngs.mjs \
 *     docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.fig01-full-story.mmd
 */

import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = path.resolve(__dirname, "..", "..");
const MMDC = path.join(
  PKG_ROOT,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "mmdc.cmd" : "mmdc",
);
const DEFAULT_WIDTH = 1920;
const DEFAULT_SCALE = 2;

/** Vertical bands as fractions of full diagram height (fig01 viewBox-aligned). */
const FIG01_SLICES = [
  {
    suffix: "slide01-upstream",
    label: "A-C: detections through S3 handoff",
    topFrac: 0,
    bottomFrac: 828 / 1961.850830078125,
  },
  {
    suffix: "slide02-aws-pipeline",
    label: "D-E: AWS pipeline and analyst review",
    topFrac: 820 / 1961.850830078125,
    bottomFrac: 1,
  },
];

/** 16:9 crops from the A-C upstream slide for direct PowerPoint insertion. */
const FIG01_UPSTREAM_16_9_SLICES = [
  {
    suffix: "slide01-upstream-part01-authoring-live",
    label: "A-B: detection authoring and alert start",
    topFrac: 0,
  },
  {
    suffix: "slide01-upstream-part02-live-handoff",
    label: "B-C: notable bundling and handoff",
    topFrac: 560 / 2580,
  },
  {
    suffix: "slide01-upstream-part03-handoff-pipeline-entry",
    label: "C-D: handoff into the AWS pipeline",
    topFrac: 1220 / 2580,
  },
];

function runMmdc(mmdPath, pngPath, width, scale) {
  const args = [
    "-i",
    mmdPath,
    "-o",
    pngPath,
    "-b",
    "white",
    "-w",
    String(width),
    "-s",
    String(scale),
    "-q",
  ];
  const result = spawnSync(MMDC, args, {
    cwd: PKG_ROOT,
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    throw new Error(
      `mmdc failed: ${result.stderr || result.stdout || "unknown error"}`,
    );
  }
}

function cropFig01Slides(fullPngPath, base) {
  const py = `import sys
from PIL import Image
img = Image.open(sys.argv[1])
w, h = img.size
slices = sys.argv[2].split(";")
for spec in slices:
    suffix, top_f, bot_f = spec.split("|")
    top = max(0, int(round(float(top_f) * h)))
    bottom = min(h, int(round(float(bot_f) * h)))
    out = sys.argv[3] + suffix + ".png"
    crop = img.crop((0, top, w, bottom))
    target_w = int(sys.argv[4])
    if crop.width != target_w:
        new_h = max(1, int(round(crop.height * (target_w / crop.width))))
        crop = crop.resize((target_w, new_h), Image.Resampling.LANCZOS)
    crop.save(out)
    print(out)
`;
  const sliceSpec = FIG01_SLICES.map(
    (s) => `${s.suffix}|${s.topFrac}|${s.bottomFrac}`,
  ).join(";");
  const outPrefix = `${base}.ppt-`;
  const result = spawnSync(
    process.platform === "win32" ? "python" : "python3",
    ["-c", py, fullPngPath, sliceSpec, outPrefix, String(DEFAULT_WIDTH)],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(result.stderr || "Pillow crop failed (pip install pillow)");
  }
  for (const line of (result.stdout || "").trim().split("\n")) {
    if (line) {
      const slice = FIG01_SLICES.find((s) => line.includes(s.suffix));
      console.log(`Wrote ${line.trim()}${slice ? ` (${slice.label})` : ""}`);
    }
  }
}

function cropFig01Upstream16x9Slides(upstreamPngPath, base, targetWidth) {
  const py = `import sys
from PIL import Image
img = Image.open(sys.argv[1])
w, h = img.size
target_w = int(sys.argv[3])
target_h = int(round(target_w * 9 / 16))
if w != target_w:
    new_h = max(1, int(round(h * (target_w / w))))
    img = img.resize((target_w, new_h), Image.Resampling.LANCZOS)
    w, h = img.size
slices = sys.argv[2].split(";")
for spec in slices:
    suffix, top_f = spec.split("|")
    top = max(0, min(h - target_h, int(round(float(top_f) * h))))
    bottom = min(h, top + target_h)
    out = sys.argv[4] + suffix + ".png"
    crop = img.crop((0, top, w, bottom))
    crop.save(out)
    print(out)
`;
  const sliceSpec = FIG01_UPSTREAM_16_9_SLICES.map(
    (s) => `${s.suffix}|${s.topFrac}`,
  ).join(";");
  const outPrefix = `${base}.ppt-`;
  const result = spawnSync(
    process.platform === "win32" ? "python" : "python3",
    ["-c", py, upstreamPngPath, sliceSpec, String(targetWidth), outPrefix],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(result.stderr || "Pillow crop failed (pip install pillow)");
  }
  for (const line of (result.stdout || "").trim().split("\n")) {
    if (line) {
      const slice = FIG01_UPSTREAM_16_9_SLICES.find((s) =>
        line.includes(s.suffix),
      );
      console.log(`Wrote ${line.trim()}${slice ? ` (${slice.label})` : ""}`);
    }
  }
}

function resolveMmdPath(inputPath) {
  if (inputPath.endsWith(".mmd")) {
    return inputPath;
  }
  if (inputPath.endsWith(".svg")) {
    const mmd = inputPath.replace(/\.svg$/i, ".mmd");
    if (fs.existsSync(mmd)) {
      return mmd;
    }
    throw new Error(
      `No .mmd next to SVG. Add ${path.basename(mmd)} or pass the .mmd file.`,
    );
  }
  throw new Error("Input must be .mmd or .svg with a sibling .mmd");
}

function exportFig01(mmdPath, width, scale) {
  const base = mmdPath.replace(/\.mmd$/i, "");
  const fullOut = `${base}.ppt-full.png`;
  runMmdc(mmdPath, fullOut, width, scale);
  console.log(`Wrote ${fullOut} (mmdc, width=${width}, scale=${scale})`);
  cropFig01Slides(fullOut, base);
  cropFig01Upstream16x9Slides(`${base}.ppt-slide01-upstream.png`, base, width);
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 0 || args.includes("-h") || args.includes("--help")) {
    console.log(
      "Usage: node export_svg_to_ppt_pngs.mjs <fig01.mmd|.svg> [--width 1920] [--scale 2]",
    );
    process.exit(args.length === 0 ? 1 : 0);
  }

  let width = DEFAULT_WIDTH;
  let scale = DEFAULT_SCALE;
  const fileArgs = [];
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === "--width" && args[i + 1]) {
      width = Number(args[++i]);
    } else if (args[i] === "--scale" && args[i + 1]) {
      scale = Number(args[++i]);
    } else {
      fileArgs.push(args[i]);
    }
  }

  for (const rel of fileArgs) {
    const inputPath = path.isAbsolute(rel)
      ? rel
      : path.resolve(process.cwd(), rel);
    if (!fs.existsSync(inputPath)) {
      throw new Error(`File not found: ${inputPath}`);
    }
    const mmdPath = resolveMmdPath(inputPath);
    const name = path.basename(mmdPath);
    if (name.includes("fig01-full-story")) {
      exportFig01(mmdPath, width, scale);
    } else {
      const outPath = mmdPath.replace(/\.mmd$/i, ".ppt.png");
      runMmdc(mmdPath, outPath, width, scale);
      console.log(`Wrote ${outPath}`);
    }
  }
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
