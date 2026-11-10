/**
 * Lightweight copies of the site's images.
 *
 * WHY THIS EXISTS
 * ---------------
 * The artwork in public/ is kept at full quality (several files are 6-7 MB).
 * Served as-is, the Case Studies page alone sent 40 MB of images to a phone.
 * This script writes small WebP copies of every image the site uses into
 * public/img/, at a few widths, and records them in src/data/images.json.
 * The <Img> component (src/components/Img.tsx) reads that file and lets the
 * browser pick the smallest copy that is still sharp on its screen.
 *
 * The originals are never changed or removed: existing links to them keep
 * working, and "open full size" on an article still shows the master.
 *
 * WHEN TO RUN IT
 * --------------
 * After adding or replacing an image in public/. It is NOT part of the site
 * build (the build must not depend on a native image library), so the output
 * is committed:
 *
 *     npm install --no-save sharp
 *     node scripts/optimize-images.mjs
 *     git add public/img src/data/images.json
 *
 * An image that has no entry in images.json still works: <Img> then serves
 * the original file, exactly as a plain <img> would.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { basename, extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const PUBLIC = join(ROOT, 'public');
const OUT = join(PUBLIC, 'img');
const MANIFEST = join(ROOT, 'src', 'data', 'images.json');

// Folders under public/ whose images the pages show.
const SOURCE_DIRS = ['', 'certificates'];
const RASTER = new Set(['.jpg', '.jpeg', '.png']);

// Widths (px) written for a normal content image, and for an image that is
// only ever shown small (logo, portraits). A width at or above the source's
// own is skipped, and the source's width (capped at the largest step) is
// always included, so nothing is ever upscaled.
const CONTENT_WIDTHS = [480, 800, 1280, 1600];
const SMALL_WIDTHS = [96, 240, 480];
const SMALL_IMAGES = new Set([
  'Logo.jpg', 'Adam.jpg', 'Ammar.jpg', 'Bakr.png', 'Bassam.jpg', 'John.jpg', 'Sherif.jpg', 'Zaeem.jpg',
]);

// Link-preview image for articles (LinkedIn and X refuse images over 5 MB,
// which the full-quality artwork is). Only written when the original is
// heavy; a small original is already a fine preview.
const OG_WIDTH = 1200;
const OG_MIN_SOURCE_BYTES = 300_000;

const walk = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
  );

// Everything the site could reference an image from.
const sourceText = [
  ...walk(join(ROOT, 'src')).filter((f) => /\.(tsx?|json)$/.test(f) && f !== MANIFEST),
  join(ROOT, 'index.html'),
]
  .map((f) => readFileSync(f, 'utf8'))
  .join('\n');
const articleMeta = readFileSync(join(ROOT, 'src', 'lib', 'articleMeta.ts'), 'utf8');

const widthsFor = (name, sourceWidth) => {
  const ladder = SMALL_IMAGES.has(name) ? SMALL_WIDTHS : CONTENT_WIDTHS;
  const top = Math.min(sourceWidth, ladder[ladder.length - 1]);
  return [...ladder.filter((w) => w < top), top];
};

const isFresh = (out, src) => existsSync(out) && statSync(out).mtimeMs >= statSync(src).mtimeMs;

mkdirSync(OUT, { recursive: true });
const manifest = {};
let written = 0;
let kept = 0;
let bytesBefore = 0;
let bytesAfter = 0;

for (const dir of SOURCE_DIRS) {
  const abs = join(PUBLIC, dir);
  for (const file of readdirSync(abs).sort()) {
    const ext = extname(file).toLowerCase();
    if (!RASTER.has(ext)) continue;
    const src = join(abs, file);
    const url = '/' + relative(PUBLIC, src).split('\\').join('/');
    if (!sourceText.includes(url)) continue; // not shown anywhere on the site

    const meta = await sharp(src).metadata();
    const stem = (dir ? dir + '-' : '') + basename(file, extname(file));
    const widths = widthsFor(file, meta.width);
    const variants = [];
    for (const w of widths) {
      const outName = `${stem}-${w}.webp`;
      const out = join(OUT, outName);
      if (!isFresh(out, src)) {
        await sharp(src)
          .resize({ width: w, withoutEnlargement: true })
          // smartSubsample keeps small text and thin lines in the infographics crisp.
          .webp({ quality: 82, effort: 6, smartSubsample: true })
          .toFile(out);
        written++;
      } else {
        kept++;
      }
      variants.push([w, `/img/${outName}`]);
    }

    const entry = {
      w: meta.width,
      h: meta.height,
      src: variants[variants.length - 1][1],
      srcset: variants.map(([w, u]) => `${u} ${w}w`).join(', '),
    };

    if (articleMeta.includes(`'${url}'`) && statSync(src).size > OG_MIN_SOURCE_BYTES) {
      const outName = `${stem}-og.jpg`;
      const out = join(OUT, outName);
      if (!isFresh(out, src)) {
        await sharp(src)
          .resize({ width: OG_WIDTH, withoutEnlargement: true })
          .flatten({ background: '#ffffff' })
          .jpeg({ quality: 84, mozjpeg: true })
          .toFile(out);
        written++;
      } else {
        kept++;
      }
      entry.og = `/img/${outName}`;
    }

    manifest[url] = entry;
    bytesBefore += statSync(src).size;
    bytesAfter += statSync(join(OUT, basename(entry.src))).size;
  }
}

writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + '\n');
const mb = (n) => (n / 1e6).toFixed(1) + ' MB';
console.log(
  `  [images] ${Object.keys(manifest).length} images: ${written} files written, ${kept} already current.`,
);
console.log(`  [images] originals ${mb(bytesBefore)} -> largest copies ${mb(bytesAfter)}.`);
