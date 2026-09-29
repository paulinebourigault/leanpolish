# Provenance and licenses of the frontier-prover inputs

## Seed-Prover 1.5 (Putnam 2025)
- Source: `Putnam2025.zip` in https://github.com/ByteDance-Seed/Seed-Prover at commit
  `ac61b7dde308c889c44483e91216045990c10c63` (zip sha256 `efca87678d8ad9a8fd4e807ffa71b2e456c8f7aae0e9f1d0506163de47a3b693`).
- License: Apache License 2.0 (upstream LICENSE copied verbatim to `licenses/Seed-Prover.LICENSE.Apache-2.0.txt`).
- The released data (`experiments/frontier_hybrid` on the dataset) contains the unmodified inputs (`files/seed/orig/`)
  and modified versions (`lp/`, `base/`, `run_*/final/`: shortened by LeanPolish and/or the neural editor).
  This notice states that change, as Apache-2.0 section 4(b) requires.
- sha256 of the unmodified inputs:
```
5730608eaa81b546bbdc9891e714887c37babbb9e170113ca4f14f2fda1ef254  A1.lean
bd55ec1cddd00b7db20e1fbcf794d5349fc7ed89e5c70ad0fab3c604eaee9297  A2.lean
9c9b12ebf32daf441f48c22f0ca6ddf1a9b39a3ed96d5f375847d7b9ee42750e  A4.lean
5ee56ef19aa1f1a1cef90c08edc12585517c9bc4fc3945afe1766aa31eef68ea  A6.lean
878fb860f5d25aae409a6eab78f93391c8ffa905d5c222307dfb44d7cf02cb4a  B2.lean
63817b0c148e68e04acfa6514836a8ab3cc167079bf2f723cdb526ccbf891ee1  B4.lean
```

## Aristotle (IMO 2025)
- Source: https://github.com/harmonic-ai/IMO2025 at commit `72b62405a176a7eaeadb335a7fa6ee80b6667161`
  (files P3 and P5; auxiliary modules `HarmonicLean.{Imports,Attrs}` from the same commit).
- The upstream repository has no LICENSE file at that commit. The Aristotle proof files, whole-file
  derivatives of them, and proof spans taken from them are therefore **not redistributed** in this archive;
  only aggregate token counts appear in `results/`. To rebuild, fetch the upstream commit, stage it with
  `scripts/prep_files.sh`, and check these sha256 values:
```
a532e7d57c952d19064346e768160b2b011071e3535d7514884d979361f52af8  P3.lean
583f24f0f9c8e30c97467f59ce6891fa949d5799786ac6bc2eddbc115486ffc3  P5.lean
```
