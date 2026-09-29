---
name: optimize-images
description: Optimize PNG assets when the user asks to reduce image size or adds PNGs that need compression, preserving each source in a sibling originals/ directory for manual review and deletion.
---

# Optimize images

Use the bundled script to replace requested PNGs with smaller versions while keeping reviewable originals beside them.

## 1. Resolve the scope

Identify the exact PNG files or directories named by the user. If the request follows newly added image work, include only those new or changed PNGs. Pass explicit paths rather than optimizing the repository broadly.

**Completion criterion:** every path passed to the script belongs to the user's requested image scope.

## 2. Optimize

Resolve [`scripts/optimize_png.sh`](scripts/optimize_png.sh) relative to this `SKILL.md` and run:

```bash
bash <skill-dir>/scripts/optimize_png.sh <png-or-directory> [...]
```

The script requires `pngquant` and `optipng` in `PATH`. Keep them external to the target project; do not add image-optimization dependencies to project manifests.

For each successful file `path/image.png`, the script:

- writes the untouched source to `path/originals/image.png`;
- writes the optimized image back to `path/image.png`;
- preserves dimensions and transparency;
- replaces the source only when the result is smaller.

An existing `originals/image.png` is a review lock. Leave both files unchanged and report that the user must review or remove the existing backup before another optimization pass. Never delete or overwrite files in `originals/`.

Optional tuning is available through `PNG_QUALITY`, `PNG_SPEED`, `OPTIPNG_LEVEL`, and `PNG_REOPTIMIZE`. Prefer the defaults unless the user requests a quality trade-off.

**Completion criterion:** every successfully optimized PNG has a same-named original in its sibling `originals/` directory, unchanged dimensions, and a smaller byte size.

## 3. Inspect the outputs

Read every optimized image produced in this run. Compare it with the corresponding file in `originals/` when text, gradients, transparency edges, or photographs could show quantization artifacts. Restore the original from `originals/` if the optimized image has visible degradation, while retaining the backup for user review.

Run the target repository's required non-destructive checks when asset paths or build-copy configuration changed.

**Completion criterion:** every optimized output was visually inspected, and applicable repository checks passed or their failures are reported.

## 4. Report

Report:

- optimized file paths;
- original backup paths;
- byte reduction for each file and total reduction;
- checks performed;
- that files under `originals/` remain for the user's manual deletion.
