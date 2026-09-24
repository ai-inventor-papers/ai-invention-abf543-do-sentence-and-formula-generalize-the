# Peer Agreement as a Reference-Free Signal of NL→FOL Faithfulness, and Where It Fails

This folder is the finished paper plus its public web page.

## Layout

- `index.html`: the paper's project page. One self-contained file with inline CSS and JS. It loads nothing from the network and references only `figures/`.
- `interactive.html`: the explorable companion page. One self-contained file (inline CSS, JS and JSON data extracted from the run's experiment outputs, provenance listed in its footer). Its only external reference is the method diagram `figures/fig2_v0.jpg`; it loads nothing from the network. Every chart is computed in the browser from the embedded per-item scores and labels.
- `paper.tex`: the paper source. Every number on the page comes from this file.
- `paper.pdf`: the compiled paper.
- `references.bib`: the bibliography.
- `figures/`: figures used by the paper. `fig*_v0.pdf` are vector originals. `fig1/3/4/5_v0.png` are 200-DPI renders of those PDFs, made for the web page. `fig2_v0.jpg` is the method diagram. `fig*_spec.json` are the chart specs.
- `workspace/`: scratch folder from the LaTeX build (not used by the page).
- `.aii/manifest.yaml`: storage manifest (empty: nothing heavy to keep or delete).

## Viewing the page

Open `index.html` in a browser, or serve the folder:

```bash
python3 -m http.server 8000   # then open http://localhost:8000/index.html
```

## Regenerating the figure PNGs

```bash
cd figures && for f in fig1 fig3 fig4 fig5; do pdftoppm -png -r 200 -singlefile ${f}_v0.pdf ${f}_v0; done
```

## Restoring removed files

Nothing was marked `delete` in the manifest. The page was checked with a temporary Playwright
Chromium install that was deleted afterwards. To recreate it:

```bash
uv venv .tools/venv && VIRTUAL_ENV=.tools/venv uv pip install playwright
PLAYWRIGHT_BROWSERS_PATH=.tools/browsers .tools/venv/bin/playwright install chromium
```
