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

Then make the key available as an environment variable. **macOS / Linux:**

```bash
export GEMINI_API_KEY=your-key-here
```

**Windows (Command Prompt):**

```
set GEMINI_API_KEY=your-key-here
```

**Windows (PowerShell):**

```powershell
$env:GEMINI_API_KEY = "your-key-here"
```

This only applies to the terminal window you type it in — open a new one and
you must set it again. If the pipeline prints
`! GEMINI_API_KEY is not set`, that is what happened.

Optionally pin a different model (the default is `gemini-3.6-flash`):

```bash
export GEMINI_MODEL=gemini-3.6-pro
```

If the key is missing or the API is unavailable the run does not fail — it
falls back to the offline rule classifier and reports `decided_by: "rule"`
so the degradation is visible in the output.

---

## Project structure

```
.
├── sdoc/                  # the pipeline package
│   ├── schemas.py         # shared data contract — all stages import this
│   ├── loader.py          # dataset access (supplied by organisers)
│   ├── pipeline.py        # stage orchestration
│   ├── submission.py      # results -> submission.json
│   ├── classify/          # stage 1: email classification
│   ├── extract/           # stage 2: document field extraction
│   └── compare/           # stage 3: normalisation + field comparison
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
