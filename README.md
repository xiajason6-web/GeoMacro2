# China Tech Flows — semiconductor indigenization tracker

A boring, auditable pipeline that measures how fast China's wafer-fab-
equipment market is going domestic, from primary sources:

- **Collectors** (one script per source): Eurostat, Japan e-Stat, US Census
  mirror trade; cninfo filings; ECB FX; Federal Register (BIS Entity List);
  gov.cn policy library; ASML investor relations.
- **Extraction**: Claude API calls with strict JSON schemas, validated
  before any database write; failures land in a review queue, never in the
  data. LLMs never do arithmetic on the numbers.
- **Storage**: one SQLite file. Every metric row points at the exact
  archived source document (URL + sha256 + retrieval time).
- **Analysis**: deterministic pandas. The flagship series is the quarterly
  indigenization ratio: domestic equipment revenue / (domestic + imports).
- **Interpretation**: a hand-written transmission-mechanism map
  (events → channels → exposed entities), a weekly digest DRAFT, and a
  red-team memo that argues against the house thesis using our own data.
  A human reviews and publishes; the system never does.

> Research analysis only — transmission mechanisms and exposure, not
> investment advice.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # add your keys
.venv/bin/python phase0_hello.py            # end-to-end smoke test
.venv/bin/python -m pytest tests/           # fixture tests
.venv/bin/streamlit run streamlit_app.py    # dashboard
```

Methodology and known biases: [analysis/methodology.md](analysis/methodology.md).
