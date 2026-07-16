# alethic.dev Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the one-page site at alethic.dev whose job is turning a cold skeptic into someone who runs `pip install alethic-kernel` — with a demo that runs the real kernel in the visitor's browser and refuses a real proposal.

**Architecture:** Static Astro site, zero JS except the demo. Pyodide loads *on first interaction only* and runs a vendored, version-pinned `alethic_kernel` wheel client-side. No server, no API — deliberately: a hosted demo endpoint would be an unauthenticated shared kernel, which is exactly the vulnerability the kernel's HTTP API still has. Presets, not a REPL. Every preset's expected outcome is asserted in CI against the shipped wheel, so the page can never claim a refusal the code does not produce.

**Tech Stack:** Astro 5, TypeScript, Pyodide 0.28.0 (CDN, SRI-pinned), Playwright (preset assertions), Vercel (static deploy), GitHub Actions.

## Global Constraints

- **Repo:** `alethicdev/alethic-dev` (new, separate from the kernel per spec §3 — the kernel ships to PyPI and must not carry site assets; the site deploys on every push and must not be gated by the kernel's CI).
- **Deploy target:** Vercel. `alethic.dev` already delegates to `ns1/ns2.vercel-dns.com` and returns 404 — DNS is done, nothing is deployed.
- **BUILD NOW, DEPLOY LATER.** The kernel repo is **private** and `alethic-kernel` is **not on PyPI** (verified 404). Every `pip install` CTA and every `github.com/alethicdev/alethic` link is **dead until Emil goes public**. Do not deploy to production. Task 8 gates this explicitly.
- **Pyodide version:** `0.28.0` exactly. Verified working end-to-end in a real browser (~700ms load, ~970ms to installed wheel). Do not bump without re-verifying.
- **Pyodide CDN tag MUST carry SRI:**
  `integrity="sha384-aD6ek5pFVnSSMGK0qubk9ZJdMYGjPs8F6jdJaDJiyZbTcH9jLWR4LJNJ7yY430qI"` and `crossorigin="anonymous"`. Computed from `https://cdn.jsdelivr.net/pyodide/v0.28.0/full/pyodide.js`.
- **`pyodide.loadPackage(["micropip", "sqlite3"])` is REQUIRED.** `alethic_kernel/alethic/__init__.py` eagerly imports `SqliteStore` → `sqlite3`, which Pyodide unvendors. Without it: `ModuleNotFoundError: No module named 'sqlite3'`.
- **Wheel is served from our own origin** (`/public/`), pinned per deploy, never floating, never from a CDN.
- **Claims are scoped to the library, in-process.** Forbidden copy: "production-ready", anything instructing the reader to deploy the HTTP API, anything implying multi-tenancy or hosted use. The HTTP API has **zero authentication** and `role` is read from the request body — a caller can claim `kernel` and commit without validation. Those are real, open blockers (P0-1, P0-2).
- **Benchmark copy must state its scope inline:** self-run, 6 Stripe refund tasks × 50 seeds × 4 agents = 1,200 episodes, controlled perturbations. An unqualified "100% / 0%" reads as marketing.
- **Node:** 20+. **Package manager:** npm.

---

## Verified Kernel Facts (do not re-derive; these were measured)

Kernel API, exact signatures:

```python
Kernel(min_confidence=0.5, conflict_confidence_threshold=0.7, store=None)
kernel.write(role, slot, mode, kind, payload, trace_id,
             input_refs=None, confidence=None, ttl_ms=None,
             evidence_refs=None, scope="episode") -> Record   # Record.id
kernel.commit_belief_from_proposal(proposal_id, trace_id) -> tuple[bool, str]
kernel.commit_action_from_proposal(proposal_id, trace_id, require_prediction=False) -> tuple[bool, str]
kernel.current_view(trace_id, include_persistent=False) -> dict
```

**Preset outcomes — measured against the real kernel, not guessed:**

| preset | setup | outcome |
|---|---|---|
| `clean` | percept `confidence=0.9`, not stale, no conflict | `(True, 'COMMITTED')` |
| `low_confidence` | percept `confidence=0.3` | `(False, 'LOW_CONFIDENCE')` |
| `stale` | percept `stale=True` | `(False, 'STALE_EVIDENCE')` |
| `conflict` | percept `conflict=True`, `confidence=0.3` | `(False, 'UNRESOLVED_CONFLICT')` |
| `arbitrated` | percept `conflict=True`, `confidence=0.9` | `(True, 'COMMITTED')` |
| `duplicate_blocked` | constraint `no_duplicate_refund` + action `is_duplicate=True` | `(False, 'NO_DUPLICATE_REFUND_BLOCKED')` |
| `action_allowed` | same constraint, `is_duplicate=False` | `(True, 'COMMITTED')` |

`arbitrated` is included deliberately: it shows the kernel is not a blunt rejector — a high-confidence source overrides a conflict (`conflict_confidence_threshold=0.7`). A page that only ever shows refusals misrepresents the product.

---

## File Structure

```
alethic-dev/
  package.json                    Astro 5, TS, Playwright. Node 20+.
  astro.config.mjs                static output; no integrations needed
  vercel.json                     static build; long cache for the wheel
  tsconfig.json
  .gitignore                      node_modules, dist, .astro, test-results
  README.md                       what this is; the deploy gate (Task 8)
  scripts/
    vendor-wheel.sh               build the kernel wheel, copy to public/, write wheel.json
  public/
    alethic_kernel-<ver>-py3-none-any.whl    vendored, pinned, committed
    wheel.json                    {"file": "...whl", "version": "0.1.0"} — single source of truth
  src/
    pages/index.astro             the only page; composes the sections
    components/
      Hero.astro                  headline, install CTA, DOI badge
      Demo.astro                  demo shell: preset picker, Run, output, static fallback
      Benchmark.astro             results table + scope caveat
      HowItWorks.astro            diagram + PROPOSE/COMMIT explanation
      Paper.astro                 DOI, paper link, artifact repo
      Footer.astro                links out
    lib/
      presets.ts                  the 7 presets: label, blurb, python source, expected outcome
      runner.ts                   Pyodide boot + execute; lazy, idempotent, typed result
    styles/global.css             design tokens + layout
  tests/
    presets.spec.ts               Playwright: each preset in a real browser == expected outcome
    fallback.spec.ts              Playwright: WASM blocked -> static trace still renders
  .github/workflows/ci.yml        build + Playwright + link check
```

Each file has one job. `presets.ts` is data only — no DOM, no Pyodide — so the CI assertion and the UI consume the same single source of truth. `runner.ts` knows nothing about presets; it takes Python source and returns a result.

---

### Task 1: Repo, Astro scaffold, and a building page

**Files:**
- Create: `package.json`, `astro.config.mjs`, `tsconfig.json`, `.gitignore`, `vercel.json`, `src/pages/index.astro`, `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `npm run build` emitting `dist/index.html`. All later tasks add to `src/`.

- [ ] **Step 1: Create the repo and clone it**

```bash
gh repo create alethicdev/alethic-dev --private \
  --description "alethic.dev — the public site for the Alethic kernel"
cd /tmp/claude-1000/-home-emil/7a1d6c0c-24ba-4d44-9e21-570c029e9df6/scratchpad
gh repo clone alethicdev/alethic-dev alethic-dev
cd alethic-dev
```

- [ ] **Step 2: Write package.json**

```json
{
  "name": "alethic-dev",
  "private": true,
  "type": "module",
  "engines": { "node": ">=20" },
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "test": "playwright test",
    "vendor:wheel": "bash scripts/vendor-wheel.sh"
  },
  "devDependencies": {
    "@playwright/test": "^1.49.0",
    "astro": "^5.0.0",
    "typescript": "^5.7.0"
  }
}
```

- [ ] **Step 3: Write astro.config.mjs, tsconfig.json, .gitignore, vercel.json**

`astro.config.mjs`:
```js
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://alethic.dev',
  output: 'static',
  build: { assets: 'assets' },
});
```

`tsconfig.json`:
```json
{ "extends": "astro/tsconfigs/strict" }
```

`.gitignore`:
```
node_modules/
dist/
.astro/
test-results/
playwright-report/
```

`vercel.json` — the wheel is content-addressed by its filename, so it can cache hard:
```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "astro",
  "headers": [
    {
      "source": "/(.*).whl",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }
      ]
    }
  ]
}
```

- [ ] **Step 4: Write a placeholder index.astro so the build has something to emit**

```astro
---
const title = 'Alethic — a governed cognition framework for AI systems';
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
  </head>
  <body>
    <main><h1>Alethic</h1></main>
  </body>
</html>
```

- [ ] **Step 5: Install and build — verify it emits**

```bash
npm install
npm run build
test -f dist/index.html && echo "BUILD OK"
```
Expected: `BUILD OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Scaffold Astro site for alethic.dev

Static output, no integrations. Vercel config caches the wheel immutably,
since it is pinned per deploy and its filename carries the version."
git push -u origin main
```

---

### Task 2: Vendor the kernel wheel

**Files:**
- Create: `scripts/vendor-wheel.sh`, `public/wheel.json`, `public/alethic_kernel-0.1.0-py3-none-any.whl`

**Interfaces:**
- Consumes: the kernel repo at `../app` (clone of `alethicdev/alethic`).
- Produces: `public/wheel.json` → `{"file": "alethic_kernel-0.1.0-py3-none-any.whl", "version": "0.1.0"}`. `runner.ts` (Task 5) and `presets.spec.ts` (Task 7) both read this. It is the single source of truth for which kernel the page runs.

- [ ] **Step 1: Write scripts/vendor-wheel.sh**

The wheel is committed, not built at deploy time: Vercel has no Python, and a
pinned binary is the point — the page must run one known kernel, not whatever
`main` happens to be.

```bash
#!/usr/bin/env bash
# Build the kernel wheel and vendor it into public/.
# Usage: bash scripts/vendor-wheel.sh /path/to/alethic-kernel-repo
set -euo pipefail

KERNEL_REPO="${1:-../app}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f "$KERNEL_REPO/pyproject.toml" ]; then
  echo "error: no kernel repo at $KERNEL_REPO" >&2
  exit 1
fi

TMP="$(mktemp -d)"
python3 -m pip install --quiet build
python3 -m build --wheel --outdir "$TMP" "$KERNEL_REPO" >/dev/null

WHEEL="$(basename "$(ls "$TMP"/*.whl | head -1)")"
VERSION="$(echo "$WHEEL" | sed -E 's/^alethic_kernel-([^-]+)-.*/\1/')"

rm -f "$HERE"/public/*.whl
cp "$TMP/$WHEEL" "$HERE/public/$WHEEL"
printf '{\n  "file": "%s",\n  "version": "%s"\n}\n' "$WHEEL" "$VERSION" > "$HERE/public/wheel.json"

echo "vendored $WHEEL (version $VERSION)"
```

- [ ] **Step 2: Run it against the kernel repo**

```bash
mkdir -p public
bash scripts/vendor-wheel.sh /tmp/claude-1000/-home-emil/7a1d6c0c-24ba-4d44-9e21-570c029e9df6/scratchpad/app
cat public/wheel.json
ls -la public/*.whl
```
Expected: `vendored alethic_kernel-0.1.0-py3-none-any.whl (version 0.1.0)`, and `wheel.json` contains that filename and `"version": "0.1.0"`.

- [ ] **Step 3: Commit**

```bash
chmod +x scripts/vendor-wheel.sh
git add -A
git commit -m "Vendor the kernel wheel, pinned per deploy

Committed rather than built at deploy time: Vercel has no Python, and the
page must run one known kernel rather than whatever main happens to be.
wheel.json is the single source of truth for which version ships."
```

---

### Task 3: Preset data — the single source of truth

**Files:**
- Create: `src/lib/presets.ts`

**Interfaces:**
- Consumes: nothing (pure data).
- Produces: `export interface Preset { id, label, blurb, code, expect: { ok: boolean, code: string } }` and `export const PRESETS: Preset[]`. Consumed by `Demo.astro` (Task 6), `presets.spec.ts` (Task 7), and the static fallback (Task 4).

Each preset's `code` is Python that ends in an expression evaluating to
`"<ok>|<code>"`. `runner.ts` returns that string; the UI parses it; CI asserts it.
Outcomes below are **measured**, not assumed — do not alter them without
re-running against the kernel.

- [ ] **Step 1: Write src/lib/presets.ts**

```ts
export interface Preset {
  id: string;
  label: string;
  blurb: string;
  /** Python whose final expression is "<True|False>|<CODE>". */
  code: string;
  expect: { ok: boolean; code: string };
}

const belief = (setup: string) => `
from alethic_kernel.alethic.kernel import Kernel
k = Kernel()
${setup}
prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
               {"value": True, "depends_on": ["charge"]}, "demo")
ok, code = k.commit_belief_from_proposal(prop.id, "demo")
f"{ok}|{code}"
`.trim();

const action = (isDuplicate: boolean) => `
from alethic_kernel.alethic.kernel import Kernel
k = Kernel()
k.write("tool", "percepts", "COMMIT", "charge",
        {"stale": False, "conflict": False}, "demo", confidence=0.9)
prop = k.write("planner", "beliefs", "PROPOSE", "refund_due",
               {"value": True, "depends_on": ["charge"]}, "demo")
k.commit_belief_from_proposal(prop.id, "demo")
k.write("symbolic_validator", "constraints", "COMMIT", "no_duplicate_refund",
        {"enabled": True, "blocks_field": "is_duplicate"}, "demo")
act = k.write("planner", "actions", "PROPOSE", "issue_refund",
              {"type": "issue_refund", "amount": 4200,
               "is_duplicate": ${isDuplicate ? 'True' : 'False'},
               "requires_beliefs": ["refund_due"]}, "demo")
ok, code = k.commit_action_from_proposal(act.id, "demo")
f"{ok}|{code}"
`.trim();

export const PRESETS: Preset[] = [
  {
    id: 'clean',
    label: 'Good evidence',
    blurb: 'A fresh, high-confidence observation. The kernel has no reason to object.',
    code: belief(`k.write("tool", "percepts", "COMMIT", "charge",
        {"stale": False, "conflict": False}, "demo", confidence=0.9)`),
    expect: { ok: true, code: 'COMMITTED' },
  },
  {
    id: 'low_confidence',
    label: 'Low confidence',
    blurb: 'The same proposal, from a source that is only 30% sure. Below the 0.5 threshold.',
    code: belief(`k.write("tool", "percepts", "COMMIT", "charge",
        {"stale": False, "conflict": False}, "demo", confidence=0.3)`),
    expect: { ok: false, code: 'LOW_CONFIDENCE' },
  },
  {
    id: 'stale',
    label: 'Stale evidence',
    blurb: 'The observation is out of date. Confident, and still refused.',
    code: belief(`k.write("tool", "percepts", "COMMIT", "charge",
        {"stale": True, "conflict": False}, "demo", confidence=0.9)`),
    expect: { ok: false, code: 'STALE_EVIDENCE' },
  },
  {
    id: 'conflict',
    label: 'Conflicting evidence',
    blurb: 'Sources disagree and none is confident enough to settle it.',
    code: belief(`k.write("tool", "percepts", "COMMIT", "charge",
        {"stale": False, "conflict": True}, "demo", confidence=0.3)`),
    expect: { ok: false, code: 'UNRESOLVED_CONFLICT' },
  },
  {
    id: 'arbitrated',
    label: 'Conflict, arbitrated',
    blurb: 'Sources disagree, but one is confident enough (>= 0.7) to override. Not a blunt rejector.',
    code: belief(`k.write("tool", "percepts", "COMMIT", "charge",
        {"stale": False, "conflict": True}, "demo", confidence=0.9)`),
    expect: { ok: true, code: 'COMMITTED' },
  },
  {
    id: 'duplicate_blocked',
    label: 'Duplicate refund',
    blurb: 'Evidence is fine. A declarative constraint blocks the action anyway.',
    code: action(true),
    expect: { ok: false, code: 'NO_DUPLICATE_REFUND_BLOCKED' },
  },
  {
    id: 'action_allowed',
    label: 'Refund allowed',
    blurb: 'The same action, not a duplicate. The constraint has nothing to say.',
    code: action(false),
    expect: { ok: true, code: 'COMMITTED' },
  },
];
```

- [ ] **Step 2: Typecheck**

```bash
npx tsc --noEmit -p tsconfig.json
```
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add src/lib/presets.ts
git commit -m "Add demo presets with measured outcomes

Outcomes come from running the real kernel, not from reading the docs.
Data only, no DOM and no Pyodide, so the UI and the CI assertion consume
one source of truth. Includes the arbitrated case: a page that only ever
shows refusals misrepresents a kernel that also knows when to say yes."
```

---

### Task 4: The static page — everything except the demo

**Files:**
- Create: `src/styles/global.css`, `src/components/Hero.astro`, `src/components/Benchmark.astro`, `src/components/HowItWorks.astro`, `src/components/Paper.astro`, `src/components/Footer.astro`
- Modify: `src/pages/index.astro`
- Copy: `public/architecture.png` (from the kernel repo's `docs/architecture.png`)

**Interfaces:**
- Consumes: nothing.
- Produces: a complete, readable page with zero JS. Task 6 inserts `<Demo />` between `<Hero />` and `<Benchmark />`.

- [ ] **Step 1: Copy the diagram**

```bash
cp /tmp/claude-1000/-home-emil/7a1d6c0c-24ba-4d44-9e21-570c029e9df6/scratchpad/app/docs/architecture.png public/architecture.png
```

- [ ] **Step 2: Write src/styles/global.css**

```css
:root {
  --bg: #0b0d10;
  --panel: #12161b;
  --line: #232a33;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #4ea1ff;
  --ok: #3fb950;
  --refuse: #f85149;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  --sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: var(--sans); line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
main { max-width: 62rem; margin: 0 auto; padding: 0 1.25rem; }
section { padding: 4rem 0; border-bottom: 1px solid var(--line); }
section:last-of-type { border-bottom: 0; }
h1, h2 { line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 1rem; }
h1 { font-size: clamp(2rem, 5vw, 3.25rem); }
h2 { font-size: clamp(1.4rem, 3vw, 2rem); }
p { margin: 0 0 1rem; }
a { color: var(--accent); }
code, pre { font-family: var(--mono); font-size: 0.9rem; }
pre {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; padding: 1rem; overflow-x: auto;
}
table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
th, td { text-align: left; padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; }
.muted { color: var(--muted); }
.small { font-size: 0.875rem; }
img { max-width: 100%; height: auto; }
```

- [ ] **Step 3: Write src/components/Hero.astro**

The install command is real but not yet publishable — Task 8 gates the deploy,
not this copy.

```astro
---
---
<section id="hero">
  <p class="muted small">A governed cognition framework for AI systems</p>
  <h1>Your model proposes.<br />Alethic decides.</h1>
  <p style="max-width: 46rem; font-size: 1.1rem;">
    Alethic sits between what an LLM <em>wants</em> to do and what it's
    <em>allowed</em> to do — validating every belief, plan, and action against
    evidence quality, confidence thresholds, and declarative constraints before
    anything gets committed.
  </p>
  <p style="max-width: 46rem;" class="muted">
    The core insight: architectural governance — not model scale — is the
    primary bottleneck for trustworthy modular AI. An LLM decides <em>what</em>
    to propose; the kernel decides <em>whether</em> the proposal meets the
    evidence standard for commitment.
  </p>
  <pre><code>pip install alethic-kernel</code></pre>
  <p class="small">
    <a href="https://doi.org/10.5281/zenodo.18691808">
      <img src="https://zenodo.org/badge/DOI/10.5281/zenodo.18691808.svg"
           alt="DOI 10.5281/zenodo.18691808" width="190" height="20" />
    </a>
  </p>
</section>
```

- [ ] **Step 4: Write src/components/Benchmark.astro**

Scope stated inline — an unqualified 100%/0% reads as marketing.

```astro
---
---
<section id="benchmark">
  <h2>Measured</h2>
  <p class="muted" style="max-width: 46rem;">
    1,200 episodes: 6 Stripe refund tasks × 50 seeds × 4 agents, with
    controlled perturbations injecting stale, conflicting, and low-confidence
    evidence. Self-run — the harness and tasks ship in the repo, so you can
    reproduce it.
  </p>
  <table>
    <thead>
      <tr><th>Agent</th><th>Task success</th><th>Unsafe actions</th><th>Unsupported beliefs</th><th>Traceability</th></tr>
    </thead>
    <tbody>
      <tr><td>string_glue</td><td>61.3%</td><td>38.7%</td><td>26.0%</td><td>0.10</td></tr>
      <tr><td>json_glue</td><td>57.0%</td><td>43.0%</td><td>31.0%</td><td>0.30</td></tr>
      <tr><td><strong>alethic</strong></td><td><strong>100%</strong></td><td><strong>0%</strong></td><td><strong>0%</strong></td><td><strong>1.00</strong></td></tr>
      <tr><td><strong>llm_bk</strong></td><td><strong>99.0%</strong></td><td><strong>0%</strong></td><td><strong>0%</strong></td><td><strong>1.00</strong></td></tr>
    </tbody>
  </table>
  <p class="muted small" style="max-width: 46rem;">
    The kernel-backed agents never act on evidence that fails validation. The
    baselines do, 39–43% of the time. <code>llm_bk</code> scores slightly lower
    on task success because it sometimes declines when acting would have been
    safe — the governance is identical regardless of planner.
  </p>
</section>
```

- [ ] **Step 5: Write src/components/HowItWorks.astro**

```astro
---
---
<section id="how">
  <h2>How it works</h2>
  <p style="max-width: 46rem;">
    Seven semantic slots hold all state. Workers read and write through two
    modes: <strong>PROPOSE</strong> (tentative, must pass validation) and
    <strong>COMMIT</strong> (finalized). Every proposal runs the validation
    pipelines — stale evidence, missing percepts, constraint violations and
    negative predictions all cause rejection rather than action.
  </p>
  <p><img src="/architecture.png" alt="Blackboard kernel architecture: seven semantic slots with PROPOSE and COMMIT paths through the validation pipelines" width="720" /></p>
</section>
```

- [ ] **Step 6: Write src/components/Paper.astro and Footer.astro**

`Paper.astro`:
```astro
---
---
<section id="paper">
  <h2>The research</h2>
  <p style="max-width: 46rem;">
    <a href="https://doi.org/10.5281/zenodo.18691808">From Fragile Glue to
    Governed Cognition</a> — a controlled study of blackboard kernels for
    modular AI systems, and the argument this kernel implements.
  </p>
  <p class="muted small">
    DOI <code>10.5281/zenodo.18691808</code> ·
    Artifacts: <a href="https://github.com/emiluzelac/governed-cognition">governed-cognition</a>
  </p>
</section>
```

`Footer.astro`:
```astro
---
---
<section id="links" style="border-bottom: 0;">
  <p class="small">
    <a href="https://github.com/alethicdev/alethic">GitHub</a> ·
    <a href="https://pypi.org/project/alethic-kernel/">PyPI</a> ·
    <a href="https://github.com/alethicdev/alethic/blob/main/docs/architecture.md">Docs</a> ·
    <a href="https://doi.org/10.5281/zenodo.18691808">Paper</a>
  </p>
  <p class="muted small">MIT licensed.</p>
</section>
```

- [ ] **Step 7: Rewrite src/pages/index.astro to compose them**

```astro
---
import '../styles/global.css';
import Hero from '../components/Hero.astro';
import Benchmark from '../components/Benchmark.astro';
import HowItWorks from '../components/HowItWorks.astro';
import Paper from '../components/Paper.astro';
import Footer from '../components/Footer.astro';

const title = 'Alethic — your model proposes, Alethic decides';
const description =
  'A governed cognition framework for AI systems. Alethic validates every belief, plan, and action against evidence quality, confidence thresholds, and declarative constraints before anything gets committed.';
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta name="description" content={description} />
    <meta property="og:title" content={title} />
    <meta property="og:description" content={description} />
    <meta property="og:type" content="website" />
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='14'>⊢</text></svg>" />
  </head>
  <body>
    <main>
      <Hero />
      <Benchmark />
      <HowItWorks />
      <Paper />
      <Footer />
    </main>
  </body>
</html>
```

- [ ] **Step 8: Build and verify zero JS**

```bash
npm run build
test -f dist/index.html && echo "BUILD OK"
grep -c "<script" dist/index.html || echo "0 script tags — zero JS confirmed"
```
Expected: `BUILD OK`, and no `<script` tags.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Add the static page: hero, benchmark, how it works, paper, links

Zero JS. The benchmark states its scope inline — an unqualified 100%/0%
reads as marketing, and the numbers are strong enough to survive being
qualified honestly."
```

---

### Task 5: The Pyodide runner

**Files:**
- Create: `src/lib/runner.ts`

**Interfaces:**
- Consumes: `/wheel.json` (Task 2) at runtime via `fetch`.
- Produces: `export async function runPython(code: string): Promise<string>` — the only export. `Demo.astro` (Task 6) calls it. Knows nothing about presets.

- [ ] **Step 1: Write src/lib/runner.ts**

Boot is lazy and memoised: the first call pays for it, later calls are instant.
`loadPackage(["micropip","sqlite3"])` is mandatory — `alethic_kernel.alethic`
eagerly imports `SqliteStore`, and Pyodide unvendors `sqlite3`.

```ts
const PYODIDE_VERSION = '0.28.0';
const PYODIDE_JS = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.js`;
const PYODIDE_SRI =
  'sha384-aD6ek5pFVnSSMGK0qubk9ZJdMYGjPs8F6jdJaDJiyZbTcH9jLWR4LJNJ7yY430qI';

declare global {
  interface Window { loadPyodide?: (opts?: unknown) => Promise<any>; }
}

let bootPromise: Promise<any> | null = null;

function loadScript(src: string, integrity: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.integrity = integrity;
    s.crossOrigin = 'anonymous';
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(s);
  });
}

async function boot(): Promise<any> {
  await loadScript(PYODIDE_JS, PYODIDE_SRI);
  if (!window.loadPyodide) throw new Error('pyodide did not register');
  const pyodide = await window.loadPyodide();

  // sqlite3 is unvendored in Pyodide, and alethic_kernel.alethic imports
  // SqliteStore eagerly — without this the first import fails.
  await pyodide.loadPackage(['micropip', 'sqlite3']);

  const meta = await fetch('/wheel.json').then((r) => {
    if (!r.ok) throw new Error(`wheel.json ${r.status}`);
    return r.json() as Promise<{ file: string; version: string }>;
  });

  const micropip = pyodide.pyimport('micropip');
  await micropip.install(`${location.origin}/${meta.file}`);

  return pyodide;
}

/** Boot Pyodide if needed, then evaluate `code`. Returns its final expression as a string. */
export async function runPython(code: string): Promise<string> {
  if (!bootPromise) bootPromise = boot().catch((e) => { bootPromise = null; throw e; });
  const pyodide = await bootPromise;
  const result = await pyodide.runPythonAsync(code);
  return String(result);
}
```

- [ ] **Step 2: Typecheck**

```bash
npx tsc --noEmit -p tsconfig.json
```
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add src/lib/runner.ts
git commit -m "Add the Pyodide runner: lazy, memoised, SRI-pinned

Boot is deferred to the first run so the static page stays instant and only
visitors who engage pay the download. loadPackage includes sqlite3 because
alethic_kernel.alethic imports SqliteStore eagerly and Pyodide unvendors it.
The CDN tag carries SRI; the wheel is fetched from our own origin."
```

---

### Task 6: The demo component

**Files:**
- Create: `src/components/Demo.astro`
- Modify: `src/pages/index.astro` (insert `<Demo />` between `<Hero />` and `<Benchmark />`)

**Interfaces:**
- Consumes: `PRESETS` (Task 3), `runPython` (Task 5).
- Produces: a `<section id="demo">` with `[data-preset]` buttons, `#demo-run`, `#demo-output`, and `[data-static-trace]` blocks. Tasks 7 asserts against these hooks.

The static trace renders server-side for every preset and is the no-JS and
Pyodide-failure experience: the story still lands, and the visitor never sees a
blank box.

- [ ] **Step 1: Write src/components/Demo.astro**

```astro
---
import { PRESETS } from '../lib/presets';
const first = PRESETS[0];
---
<section id="demo">
  <h2>Watch it refuse</h2>
  <p style="max-width: 46rem;">
    This runs the <strong>real kernel</strong> in your browser — the same wheel
    you'd install, compiled to WebAssembly. Nothing is sent anywhere. Pick a
    scenario and run it.
  </p>

  <div class="demo-grid">
    <div class="demo-presets" role="group" aria-label="Scenario">
      {PRESETS.map((p, i) => (
        <button type="button" data-preset={p.id} class:list={['preset', { active: i === 0 }]}>
          {p.label}
        </button>
      ))}
    </div>

    <div class="demo-panel">
      <p class="muted small" id="demo-blurb">{first.blurb}</p>
      <pre id="demo-code">{first.code}</pre>
      <p>
        <button type="button" id="demo-run" class="run">Run in your browser</button>
        <span class="muted small" id="demo-status"></span>
      </p>
      <pre id="demo-output"><span id="demo-live" hidden></span>{PRESETS.map((p) => (
        <span data-static-trace={p.id} hidden={p.id !== first.id}>
          &gt; kernel  {p.expect.ok ? 'COMMITTED' : 'REFUSED'}  ({p.expect.code})
        </span>
      ))}</pre>
      <noscript>
        <p class="muted small">
          These are the outcomes the kernel produces; JavaScript only lets you
          run them yourself.
        </p>
      </noscript>
    </div>
  </div>
</section>

<style>
  .demo-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 1.25rem; }
  @media (max-width: 720px) { .demo-grid { grid-template-columns: 1fr; } }
  .demo-presets { display: flex; flex-direction: column; gap: 0.4rem; }
  .preset {
    text-align: left; padding: 0.55rem 0.75rem; border-radius: 6px; cursor: pointer;
    background: var(--panel); color: var(--text);
    border: 1px solid var(--line); font: inherit; font-size: 0.9rem;
  }
  .preset:hover { border-color: var(--accent); }
  .preset.active { border-color: var(--accent); color: var(--accent); }
  .run {
    background: var(--accent); color: #06121f; border: 0; border-radius: 6px;
    padding: 0.55rem 1rem; font: inherit; font-weight: 600; cursor: pointer;
  }
  .run:disabled { opacity: 0.6; cursor: default; }
  #demo-output { min-height: 4.5rem; white-space: pre-wrap; }
  #demo-output .ok { color: var(--ok); }
  #demo-output .refuse { color: var(--refuse); }
</style>

<script>
  import { PRESETS } from '../lib/presets';
  import { runPython } from '../lib/runner';

  const byId = Object.fromEntries(PRESETS.map((p) => [p.id, p]));
  let current = PRESETS[0];

  const blurb = document.getElementById('demo-blurb')!;
  const codeEl = document.getElementById('demo-code')!;
  const out = document.getElementById('demo-output')!;
  const live = document.getElementById('demo-live')!;
  const status = document.getElementById('demo-status')!;
  const runBtn = document.getElementById('demo-run') as HTMLButtonElement;

  /** Show the recorded trace for `id` and hide the live one.
   *  The live result lives in its own element: writing over #demo-output would
   *  delete the recorded traces, and they are the fallback. */
  function showStatic(id: string) {
    live.hidden = true;
    // A stale result must not outlive the run that produced it — three presets
    // share the outcome COMMITTED, so a leftover attribute would let a test
    // (and a reader) mistake the previous run for this one.
    delete out.dataset.result;
    out.querySelectorAll('[data-static-trace]').forEach((el) => {
      (el as HTMLElement).hidden = (el as HTMLElement).dataset.staticTrace !== id;
    });
  }

  function select(id: string) {
    current = byId[id];
    blurb.textContent = current.blurb;
    codeEl.textContent = current.code;
    status.textContent = '';
    document.querySelectorAll('[data-preset]').forEach((b) => {
      b.classList.toggle('active', (b as HTMLElement).dataset.preset === id);
    });
    showStatic(id);
  }

  document.querySelectorAll('[data-preset]').forEach((b) => {
    b.addEventListener('click', () => select((b as HTMLElement).dataset.preset!));
  });

  runBtn.addEventListener('click', async () => {
    runBtn.disabled = true;
    status.textContent = 'starting python…';
    delete out.dataset.result;
    try {
      const raw = await runPython(current.code);
      const [okStr, code] = raw.split('|');
      const ok = okStr === 'True';
      out.querySelectorAll('[data-static-trace]').forEach((el) => {
        (el as HTMLElement).hidden = true;
      });
      live.innerHTML =
        `<span class="muted">&gt; PROPOSE  refund_due</span>\n` +
        `<span class="${ok ? 'ok' : 'refuse'}">&gt; kernel   ${ok ? 'COMMITTED' : 'REFUSED'}  ${code}</span>`;
      live.hidden = false;
      out.dataset.result = code;
      status.textContent = 'ran in your browser';
    } catch (e) {
      // Pyodide blocked, WASM unavailable, offline: the story still lands.
      status.textContent = "couldn't run here — showing the recorded result";
      showStatic(current.id);
    } finally {
      runBtn.disabled = false;
    }
  });
</script>
```

- [ ] **Step 2: Insert `<Demo />` into index.astro**

Add `import Demo from '../components/Demo.astro';` with the other imports, and
place `<Demo />` immediately after `<Hero />` — above the benchmark, so the
table is read as confirmation of something already witnessed.

```astro
      <Hero />
      <Demo />
      <Benchmark />
```

- [ ] **Step 3: Build and verify the static trace is server-rendered**

```bash
npm run build
grep -q 'data-static-trace="low_confidence"' dist/index.html && echo "STATIC TRACE OK"
grep -q 'LOW_CONFIDENCE' dist/index.html && echo "OUTCOME IN HTML OK"
```
Expected: both OK — proving the no-JS path carries the story.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Add the demo: presets, real kernel in the browser, static fallback

Placed above the benchmark so the table reads as confirmation of something
already witnessed rather than a claim. Presets rather than a REPL: the demo's
job is to be true, not exhaustive, and an open editor puts the kernel's edge
cases on the marketing page. Every outcome is server-rendered, so a visitor
with JS off or WASM blocked still sees what the kernel does."
```

---

### Task 7: Playwright — assert every preset against the real kernel

**Files:**
- Create: `playwright.config.ts`, `tests/presets.spec.ts`, `tests/fallback.spec.ts`

**Interfaces:**
- Consumes: the built site (`dist/`), `PRESETS` (Task 3).
- Produces: `npm test` green. This is the test that keeps the page honest — it must never claim a refusal the code does not produce.

- [ ] **Step 1: Write playwright.config.ts**

```ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 120_000,
  expect: { timeout: 60_000 },
  fullyParallel: false,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4321', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run build && npx astro preview --port 4321',
    url: 'http://127.0.0.1:4321',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
```

- [ ] **Step 2: Write tests/presets.spec.ts**

```ts
import { test, expect } from '@playwright/test';
import { PRESETS } from '../src/lib/presets';

// One browser, one Pyodide boot, all presets: booting per test would be slow
// and would test the same thing seven times.
test('every preset produces the outcome the page claims', async ({ page }) => {
  await page.goto('/');

  for (const preset of PRESETS) {
    await page.click(`[data-preset="${preset.id}"]`);
    await page.click('#demo-run');

    const out = page.locator('#demo-output');
    await expect(out).toHaveAttribute('data-result', preset.expect.code, {
      timeout: 90_000,
    });

    const text = await out.textContent();
    expect(text).toContain(preset.expect.ok ? 'COMMITTED' : 'REFUSED');
  }
});

test('the shipped wheel is the one the presets were measured against', async ({ page }) => {
  const res = await page.request.get('/wheel.json');
  expect(res.ok()).toBeTruthy();
  const meta = await res.json();
  expect(meta.file).toMatch(/^alethic_kernel-.*\.whl$/);
  const wheel = await page.request.get(`/${meta.file}`);
  expect(wheel.ok()).toBeTruthy();
});
```

- [ ] **Step 3: Write tests/fallback.spec.ts**

```ts
import { test, expect } from '@playwright/test';
import { PRESETS } from '../src/lib/presets';

test('the story survives without JavaScript', async ({ browser }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false });
  const page = await ctx.newPage();
  await page.goto('/');

  // the first preset's outcome must be in the HTML, not injected by script
  const first = PRESETS[0];
  await expect(page.locator(`[data-static-trace="${first.id}"]`)).toContainText(
    first.expect.code
  );
  await ctx.close();
});

test('a blocked Pyodide falls back instead of hanging', async ({ page }) => {
  // simulate a corporate proxy / CDN outage
  await page.route('**/cdn.jsdelivr.net/**', (r) => r.abort());
  await page.goto('/');
  await page.click('[data-preset="low_confidence"]');
  await page.click('#demo-run');

  await expect(page.locator('#demo-status')).toContainText('recorded result', {
    timeout: 60_000,
  });
  await expect(page.locator('[data-static-trace="low_confidence"]')).toContainText(
    'LOW_CONFIDENCE'
  );
});
```

- [ ] **Step 4: Install browsers and run**

```bash
npx playwright install --with-deps chromium
npm test
```
Expected: 4 passed. If a preset fails, **the page is claiming something the kernel does not do** — fix the preset data, never the assertion.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Assert every preset against the real kernel in a real browser

The page's credibility rests entirely on the demo being real, so this is the
test that matters most: if a preset's claimed outcome ever diverges from what
the shipped wheel produces, CI fails. Also covers the two ways the demo can
fail a visitor — no JS, and a blocked CDN — since a governance page that hangs
on a spinner argues against itself."
```

---

### Task 8: CI, and the deploy gate

**Files:**
- Create: `.github/workflows/ci.yml`, `scripts/check-links.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: CI green on push; an explicit, documented block on production deploy until the kernel is public and on PyPI.

- [ ] **Step 1: Write scripts/check-links.sh**

This site exists because dead links are embarrassing; it must not ship any.
While the kernel repo is private, its links 404 anonymously — expected, and the
reason `ALLOW_PRIVATE` exists.

```bash
#!/usr/bin/env bash
# Check every external link in dist/. Kernel links are allowed to 404 while the
# repo is private; ALLOW_PRIVATE=0 turns that off at publish time.
set -uo pipefail

ALLOW_PRIVATE="${ALLOW_PRIVATE:-1}"
FAIL=0

URLS=$(grep -ohE 'https://[^"'"'"' )]+' dist/index.html | sort -u)

for u in $URLS; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -L --max-time 20 "$u" || echo 000)
  case "$u" in
    *github.com/alethicdev/alethic*|*pypi.org/project/alethic-kernel*)
      if [ "$code" = "200" ]; then
        echo "  ok    $code  $u"
      elif [ "$ALLOW_PRIVATE" = "1" ]; then
        echo "  gated $code  $u  (private/unpublished — expected for now)"
      else
        echo "  FAIL  $code  $u"; FAIL=1
      fi
      ;;
    *)
      if [ "$code" = "200" ]; then echo "  ok    $code  $u"
      else echo "  FAIL  $code  $u"; FAIL=1; fi
      ;;
  esac
done

exit $FAIL
```

- [ ] **Step 2: Write .github/workflows/ci.yml**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - run: npm run build
      - run: npm test
      - name: Check links
        run: bash scripts/check-links.sh
```

- [ ] **Step 3: Write README.md — the gate**

```markdown
# alethic.dev

The public site for [Alethic](https://github.com/alethicdev/alethic), a governed
cognition framework for AI systems.

One page. Its job is to turn a cold skeptic into someone who runs
`pip install alethic-kernel`. GitHub stays canonical for the docs.

## Do not deploy to production yet

The kernel repo is **private** and `alethic-kernel` is **not on PyPI**. The
install command and the GitHub links on this page are dead until both change.
Shipping now would put broken links on the front page of a project whose whole
pitch is rigour.

Deploy when, and only when:

1. `alethicdev/alethic` is public
2. `alethic-kernel` is on PyPI (`pip install alethic-kernel` works from a clean venv)
3. `ALLOW_PRIVATE=0 bash scripts/check-links.sh` passes — no link is gated any more

## The demo

Runs the real kernel in the visitor's browser via Pyodide, against the vendored
wheel in `public/`. No server, and deliberately so: a hosted demo endpoint would
be an unauthenticated shared kernel, which is exactly the weakness the kernel's
own HTTP API still has. Client-side execution removes the tenancy problem
entirely.

Presets, not a REPL — the demo's job is to be true, not exhaustive.

Every preset's outcome is asserted in CI against the shipped wheel
(`tests/presets.spec.ts`). If one fails, the page is claiming something the
kernel does not do: fix the preset, never the assertion.

## Refreshing the kernel

```bash
bash scripts/vendor-wheel.sh /path/to/alethic-kernel-repo
npm test        # presets must still hold against the new wheel
```

## Local

```bash
npm install
npm run dev      # http://localhost:4321
npm run build
npm test
```
```

- [ ] **Step 4: Verify CI passes locally, then commit**

```bash
chmod +x scripts/check-links.sh
npm run build
bash scripts/check-links.sh
```
Expected: the zenodo, doi.org and governed-cognition links `ok 200`; the
`alethicdev/alethic` and PyPI links `gated 404` — correct until we go public.

```bash
git add -A
git commit -m "Add CI and document the deploy gate

Link checking allows the kernel repo and PyPI to 404 while private, and
ALLOW_PRIVATE=0 turns that off at publish time — so the gate is a command
rather than a memory. The README states plainly that this must not go to
production until the install command is real."
git push
```

---

## Definition of done

- [ ] `npm run build` emits `dist/index.html` with the static traces server-rendered
- [ ] `npm test` green: 7 presets execute in a real browser and match their measured outcomes; no-JS and blocked-CDN fallbacks both hold
- [ ] `bash scripts/check-links.sh` passes with only kernel/PyPI links gated
- [ ] Nothing is deployed to production
- [ ] `README.md` states the deploy gate

## Deliberately out of scope

No search, no versioned docs, no blog, no waitlist, no contact form, no analytics, no hosted API, no authentication. If any becomes worth doing it is its own decision, made later, with reasons.
