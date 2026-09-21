# Shipping Document Verification

An AI-assisted pipeline that reads a shipping operations inbox and, for every
email, decides what it is and whether the attached documents agree.

Built for the **Averis x Monash Hackathon 2026**.

> **Status:** in active development. Setup and project structure below are
> current; pipeline commands land as the stages are implemented.

---

## The problem

A shipping operations team receives everything in one inbox: requests to verify
documents, requests to prepare new shipping instructions, invoice queries,
operational updates, and spam.

For a verification request, staff manually compare a **Shipping Instruction
(SI)** — the intended shipment details — against a **draft Bill of Lading
(BL)**, to catch incorrect details before the draft is finalised. This is
repetitive, easy to get wrong, and made harder by the two documents labelling
the same field differently (`Port of Loading` vs `Load Port`, `Consignee` vs
`To the Order of`).

This system automates that check, and escalates to a human when it cannot
decide reliably.

## What it does

For every email in the inbox:

1. **Classify** into one of `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`,
   `GENERAL`, `SPAM`.
2. **Extract** — for comparison requests, read the SI and BL attachments
   (`.txt`, `.pdf`, `.docx`, `.xlsx`) and pull the shipment fields.
3. **Compare** seven fields, aligning by meaning rather than by label text:

   | Field | Example SI label | Example BL label |
   |---|---|---|
   | `shipper` | Shipper | SHIPPER |
   | `consignee` | Consignee (Non-Negotiable) | To the Order of |
   | `notify_party` | Notify | Notify Party |
   | `port_of_loading` | Port of Loading (POL) | Load Port |
   | `port_of_discharge` | POD | Discharge Port |
   | `container_count` | Total Containers | Container Count |
   | `gross_weight_kg` | Gross Wt (kgs) | Gross Weight (KG) |

4. **Report** a result of `OK`, `MISMATCH` (with exactly which fields differ),
   or `NEEDS_REVIEW` (with the reason: `wrong_doc_type`, `missing_attachment`,
   `unreadable`, or `missing_value`).

The SI is the source of truth for the comparison.

---

## Setup

### Prerequisites

- Python 3.10+
- The hackathon data bundle (`sdoc-hackathon-bundle`)
- A Google Gemini API key ([Google AI Studio](https://aistudio.google.com/app/apikey) → **Get API key**)

### 1. Clone

```bash
git clone git@github.com:szeniii/averis-monash-hackathon-2026.git
cd averis-monash-hackathon-2026
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv && source .venv/bin/activate
```

You will need to re-run `source .venv/bin/activate` each time you open a new
terminal. Your prompt shows `(.venv)` when it is active.

### 3. Add the dataset

The dataset is **not committed to this repo** — it is supplied separately by
the organisers. Extract their bundle anywhere (Downloads is fine), then run:

```bash
bash scripts/setup_data.sh
```

That searches your usual folders for the bundle, copies it into `data/`, and
confirms the result:

```
Looking for the dataset bundle...
  Found: /Users/you/Downloads/sdoc-hackathon-bundle
Copying dataset into ./data/ ...

✓ Dataset ready — 520 emails, 250 attachments.
```

If it can't find the bundle, type the command below, then **drag the
`sdoc-hackathon-bundle` folder from Finder into your terminal** — macOS fills
in the path for you — and press Enter:

```bash
bash scripts/setup_data.sh 
```

That's the whole setup — the `✓` line above confirms it worked.

### 4. Configure the AI

Classification and field extraction run on Gemini, so the pipeline needs an
API key. Never put the key in a source file — it would end up on GitHub.

Install the client:

```bash
pip install google-genai
```

Then put the key in a `.env` file in the repo root. `sdoc/config.py` reads
it at startup, and `.gitignore` keeps `.env` out of git:

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

Open `.env` and replace `your-key-here` with your real key:

```
GEMINI_API_KEY=AIza...
```

A real environment variable still wins over the file, which is how Render
supplies the key in production. If you would rather export it by hand:

```bash
export GEMINI_API_KEY=your-key-here          # macOS / Linux
```
```powershell
$env:GEMINI_API_KEY = "your-key-here"        # Windows PowerShell, this window only
```

Both entry points print which of the two they found on startup, never the
key itself:

```
GEMINI_API_KEY found (.env or environment), model gemini-3.6-flash
```

Optionally pin a different model by adding `GEMINI_MODEL` to `.env`. The
default is `gemini-3.6-flash`.

If the key is missing or the API is unavailable the run does not fail — it
falls back to the offline rule classifier and reports `decided_by: "rule"`
so the degradation is visible in the output.

---

## Project structure

```
.
├── sdoc/                  # the pipeline package
│   ├── schemas.py         # shared data contract — all stages import this
│   ├── config.py          # .env loading and key lookup
│   ├── loader.py          # dataset access (supplied by organisers)
│   ├── pipeline.py        # stage orchestration
│   ├── submission.py      # results -> submission.json
│   ├── classify/          # stage 1: email classification
│   ├── extract/           # stage 2: document field extraction
│   │   ├── llm.py         #   Gemini, reads meaning
│   │   └── labels.py      #   offline fallback, matches label text
│   ├── compare/           # stage 3: normalisation + field comparison
│   └── decide/            # stage 4: report or escalate
├── web/                   # the review app served at the deployed URL
│   ├── app.py             # FastAPI: compare, review queue, health
│   ├── demo_cases.py      # built-in pairs, so the demo needs no dataset
│   └── static/            # single-page front end
├── scripts/               # setup_data.sh, plus pipeline entry points
├── tests/                 # unit tests
├── docs/                  # architecture notes and design decisions
└── data/                  # dataset (gitignored — see Setup)
```

---

## Usage

Set `GEMINI_API_KEY` in your terminal first (see Setup step 4), then:

```bash
# Run the full inbox and write submission.json
python3 scripts/run_pipeline.py

# Score the output against the local evaluation server
python3 scripts/score.py submission.json
```

Classification results are cached in `.cache/classify.json`, so re-running
while tuning the later stages costs no API calls. Delete that file to force a
fresh classification pass.

Scoring needs the organisers' evaluation server running locally:

```bash
cd <the docker distribution folder>
docker compose up --build        # serves http://localhost:8080
```

---

## The review app

The scoreboard cannot show the part of the use case that matters most: the
report a person actually reads, and what happens when the system will not
decide on its own. `web/` is that surface.

```bash
pip install -r requirements.txt
uvicorn web.app:app --reload        # http://localhost:8000
```

Three ways in: four built-in demo pairs, a paste box, or an upload of two
files (`.txt`, `.pdf`, `.docx`, `.xlsx`). Every comparison lands in a review
queue. A case the gate escalated stays open until a person supplies the value
it could not read, at which point the case is decided again from the
corrected evidence.

It runs with no API key. Stage 2 falls back to `sdoc/extract/labels.py`,
which matches label text rather than reading meaning; set `GEMINI_API_KEY`
and the model takes over, per document, with the label reader still catching
anything the API could not answer.

| Route | What it does |
|---|---|
| `GET /` | the app |
| `GET /health` | liveness, and which extraction engine is active |
| `POST /api/compare` | compare two pasted documents |
| `POST /api/compare/upload` | compare two uploaded files |
| `GET /api/cases` | the review queue |
| `POST /api/cases/{id}/resolve` | a person supplies a value, case re-decided |
| `POST /api/cases/{id}/confirm` | a person accepts the result |
| `GET /docs` | generated API reference |

The queue is in-memory, which is the right trade for a demonstration surface:
no database to run, and a restart simply clears it.

### Deploying

`render.yaml` is a Render blueprint. In Render, **New > Blueprint**, point it
at this repo and pick the branch; it builds from `requirements.txt` and
serves `uvicorn web.app:app`. Set `GEMINI_API_KEY` in the dashboard rather
than in the file. The free plan sleeps after inactivity, so the first request
after a quiet spell takes about thirty seconds.

`Procfile` carries the same start command, so Railway and Fly work without
changes.

---

## Development

The dataset never goes in the repo. `.gitignore` excludes `data/`, any
`ground_truth.json`, and generated `submission*.json` files — please keep it
that way.

Each pipeline stage lives in its own package so work can happen in parallel.
`sdoc/schemas.py` is the shared contract between them: treat changes to it as
breaking, and tell the team before editing.

---

## Team

_Averis x Monash Hackathon 2026_
