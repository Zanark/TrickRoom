# Blender authoring handbook sources

The original authoring guide is `AUTHORING.md`. `AUTHORING-resolved.md` adds verified file/line
citations from the current implementation. Output: `..\TrickRoom-Blender-Authoring-Handbook.pdf`
and self-contained `index.html`. `edition-manifest.json` records pages, hashes and chapter starts.

## Rebuild

From the repository root, install the explicitly optional documentation dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -c requirements-lock.txt -e ".[book]"
$env:PUPPETEER_SKIP_DOWNLOAD = 'true'
npm install --prefix docs\book --no-audit --no-fund
```

`puppeteer.json` points to the installed Windows Edge executable. Adjust only if your controlled
documentation environment uses a different local browser.

```powershell
& .\docs\book\node_modules\.bin\mmdc.cmd `
  -i docs\book\diagrams\pipeline.mmd -o docs\book\diagrams\pipeline.png `
  -p docs\book\puppeteer.json -b '#161b22'
& .\docs\book\node_modules\.bin\mmdc.cmd `
  -i docs\book\diagrams\validation.mmd -o docs\book\diagrams\validation.png `
  -p docs\book\puppeteer.json -b '#161b22'
.\.venv\Scripts\python.exe tools\build_blender_handbook.py
```

The build resolves source citations through Python AST definitions, generates PDF/HTML,
requires50-100actual PDF pages, checks empty/text-overflow pages and emits review images.
Inspect those images and the final document; automated bounds do not prove readability.
The current book is an implementation-specific local engineering edition, not a promise of
universal Blender feature compatibility or a qualification of the owner's camera setup.

Current edition: see `edition-manifest.json` for the verified page count and source hashes.
It includes35chapters/workshops and175resolved implementation citations in82A5pages.
The browser check `node tools\check_handbook_html.cjs` verifies the self-contained HTML,
including all embedded figures and chapter navigation without external-image dependencies.
