---
name: ebm-researcher
description: Trigger primarily when the user's prompt begins with "/ebm". Also use when the user explicitly asks for EBM research, PICO analysis, PubMed clinical literature review, or structured evidence synthesis. Do NOT use for casual medical Q&A, general health education, or non-literature web search. This skill structures the clinical question with PICO, runs a disciplined PubMed search-widening loop, prioritizes higher-level human evidence, and synthesizes the findings into a structured Traditional Chinese report.
---

# Evidence-Based Medicine (EBM) Researcher Skill

Perform rigorous evidence-based clinical literature review and synthesis.

## Explicit Trigger Policy
Prefer explicit activation.

Use this skill when either condition is met:
1. The user's prompt begins with `/ebm`
2. The user explicitly asks for EBM research, PICO analysis, PubMed clinical literature review, 實證醫學搜尋, or structured evidence synthesis

Do not use this skill for casual medical questions, general wellness advice, or broad web search.

---

## Core Workflow
When activated, complete the full workflow before answering. Do not stop to ask the user to confirm the PICO unless the clinical question is too ambiguous to identify the population or intervention at all.

### Stage 1: Formulate the Clinical Question in PICO
Break the request into:
- **P (Patient/Population/Problem)**
- **I (Intervention/Exposure)**
- **C (Comparison)**, if applicable
- **O (Outcome)**

If the user did not state one element explicitly, infer the narrowest clinically reasonable version and note uncertainty later in the synthesis if needed.

### Stage 2: Generate the Initial PubMed Query
Construct a focused PubMed query from the PICO elements.

Guidelines:
- Prefer clinically meaningful human-searchable terms first
- Add MeSH or synonyms when they improve recall
- Add study-design terms only when they improve specificity without making the query too brittle
- Avoid over-constraining the first query with too many filters

**MeSH term tips** (for manual queries and curl fallback):
- "heart attack" → "myocardial infarction"[MeSH]
- "high blood pressure" → "hypertension"[MeSH]
- "diabetes drug" → "hypoglycemic agents"[MeSH] or "antidiabetic agents"[MeSH]
- "statin" → "hydroxymethylglutaryl-CoA reductase inhibitors"[MeSH]
- "weight loss" → "weight loss"[MeSH] or "anti-obesity agents"[MeSH]

### Stage 3: Run the Retrieval Loop with Stop-Loss

#### Primary tool: `pubmed_search.py`

**Path (local to this skill):**
```
scripts/pubmed_search.py
```

Full path: `<skill_dir>/scripts/pubmed_search.py` (resolve via your agent's skill directory)

Usage:
```bash
# Human-readable output (default)
python3 scripts/pubmed_search.py "<PubMed query>"

# JSON output (for agent-controlled formatting per ebm-guide.md)
python3 scripts/pubmed_search.py --json "<PubMed query>"

# JSON + search log (for 3-strike reporting)
python3 scripts/pubmed_search.py --json --log "<PubMed query>"
```

The script takes a raw PubMed query string as its positional argument.
No `--query` / `--max-results` flags — the script auto-strips them if a model hallucinates them.

**Script internal behavior:**
- **Phase 1 (esearch)**: Retrieves up to 50 PMIDs
- **Auto-widen**: If zero results, strips ALL field tags (`[tiab]`, `[MeSH]`, `[au]`, etc.) and retries once
- **Phase 2 (esummary + filter)**: Scores by evidence level using PubMed `PublicationType` (primary) with title keyword fallback. Applies tiered year filtering (3yr → 10yr → all). Selects top 1-5 PMIDs.
- **Phase 3 (efetch)**: Fetches full abstracts (handles structured abstracts, nested XML elements)
- **Outputs**: Saves to `/tmp/pubmed_last_results.json` (articles) and `/tmp/pubmed_search_log.json` (search rounds)

**IMPORTANT: Script auto-widen ≠ Agent 3-strike strategy (see below)**

#### Fallback: curl + NCBI E-utilities

Only if `pubmed_search.py` fails (script missing, Python error, persistent HTTP failures):

```bash
# Phase 1: esearch
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax=50&retmode=json&term=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' '<QUERY>')"
sleep 0.5
# Phase 2: esummary
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=<COMMA_SEPARATED_PMIDS>&retmode=json"
sleep 0.5
# Phase 3: efetch
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=<TOP_1_5_PMIDS>&retmode=xml"
sleep 0.5
```

Rate limit: ≥0.5s between requests. HTTP 429/503 → exponential backoff (2s → 4s). Max 2 retries.
When using curl fallback, apply the scoring rules from [references/ebm-guide.md](references/ebm-guide.md) manually after esummary.

#### Relevance and evidence rules
Unless the user explicitly asks otherwise, prefer:
1. Systematic reviews / meta-analyses
2. Randomized controlled trials
3. Prospective cohort studies
4. Retrospective cohort or case-control studies
5. Lower-level evidence only when higher-quality evidence is unavailable

Default inclusion preference:
- Human studies over animal or in vitro studies
- Directly clinically relevant outcomes over surrogate endpoints
- Population matching the user's question over loosely related populations

If retrieved studies are mostly animal, mechanistic, or off-target for the clinical question, treat that round as insufficient and broaden strategically.

#### The Directness Gate (Critical Filter)
Having papers is not the same as having evidence that answers the clinical question.

**Before accepting retrieved papers as "successful," verify directness:**

A retrieved paper is considered **directly relevant** only if ALL of these are true:
- The **Population** (P) matches or is clinically close to your PICO
- The **Intervention/Exposure** (I) is the same as your PICO (or a direct component of a fixed-dose combo if you can isolate its effect)
- The **Outcome** (O) directly addresses your clinical question
- The study design provides reasonable causal inference (RCT, cohort, or at minimum case-control — not pure animal/in vitro)

**Treat the round as "insufficient" (proceed to widen) if retrieved papers are ANY of the following:**
- **Off-target population**: e.g., you asked about cardiomyopathy, but papers are about general heart failure, myocardial ischemia, or cardiac function in healthy volunteers
- **Off-target outcome**: e.g., you asked about mortality/cardiovascular events, but papers only measure surrogate markers like blood pressure or lipid levels without clinical outcomes
- **Off-target intervention**: e.g., the paper studies a complex herbal formula containing the herb, not the herb alone, so you cannot isolate the effect of the single ingredient
- **Lower-level evidence as default**: animal-only studies, in vitro mechanistic studies, or case reports with no comparison group — unless the user explicitly asks for these
- **Indirect comparator**: the comparison group is not what the user implied (e.g., user wanted drug A vs drug B, but paper compares drug A vs placebo)

If more than half of the retrieved papers fail the directness gate, treat this as "insufficient evidence" and proceed to the next widening strategy.

#### Auto-widen vs 3-Strike: Two Different Layers

The script and the agent each have their own broadening mechanism. They operate at different levels:

**Layer 1 — Script auto-widen (transparent to agent):**
- Triggered when esearch returns 0 PMIDs
- Strips all PubMed field tags and retries once
- This is a "zero-result recovery" — if it still returns 0, the script exits

**Layer 2 — Agent 3-strike strategy (after Directness Gate failures):**
- Triggered when papers ARE retrieved but fail the Directness Gate
- The agent must apply this manually — the script does NOT do it
- Requires progressively broader query strategies (see below)

Do NOT confuse these. If the script auto-widened and still returned 0, that's not a "strike" — that's a hard zero. If the script returned papers but they fail the Directness Gate, THAT triggers the 3-strike loop.

#### The 3-strike widening strategy
A "strike" is counted when either:
- `pubmed_search.py` returns **zero papers** (even after its internal auto-widening), OR
- **Retrieved papers fail the Directness Gate** (off-target, too indirect, or too low-level to answer the clinical question)

**Check `/tmp/pubmed_search_log.json` to see what the script already tried**, so you don't repeat the same queries.

Retry with a progressively broader PubMed query in this order:

1. **Strike 1 failed → Relax narrow filters**
   - Remove `[tiab]` field tags → search all fields (note: script already does this internally on zero results; this round catches Directness Gate failures)
   - Remove date restrictions (e.g., drop `AND 2024:2026[dp]`)
   - Keep the core population + intervention + outcome concepts

2. **Strike 2 failed → Broaden terminology**
   - Simplify toward Population + Intervention only
   - Replace specific drug/disease terms with broader synonyms or class names (e.g., "semaglutide" → "GLP-1 receptor agonist")
   - Prefer broader MeSH or umbrella terms when appropriate
   - Drop outcome terms from the query if they're overly restrictive

3. **Strike 3 failed → Stop-loss**
   - Stop searching
   - Do not switch to general web search
   - Do not invent content
   - Report that no sufficiently relevant PubMed evidence was found — **even if some papers were retrieved**, if they failed the directness gate in all 3 rounds, you must report this accurately

Keep track of the exact PubMed query passed to `pubmed_search.py` in each round and why each round failed the directness gate, so they can be summarized in the final stop-loss report.

### Stage 4: Synthesize the Evidence
Once you have 1-5 relevant papers or abstracts:
1. Read them carefully
2. Compare their populations, interventions, comparators, outcomes, and study designs
3. Identify consistency, conflict, limitations, and applicability
4. Produce a structured Traditional Chinese report

For output format and wording constraints, refer to:
[references/ebm-guide.md](references/ebm-guide.md)

---

## Follow-up Questions
If the user asks follow-up questions about the EBM report you just produced:
1. Reuse the evidence already retrieved for the same task whenever possible
2. Do not guess details not supported by the retrieved papers
3. **Read the cached results first**: `cat /tmp/pubmed_last_results.json` — this contains full English abstracts from the most recent PubMed search in this session
4. **Read the search log**: `cat /tmp/pubmed_search_log.json` — this shows what queries were tried and why rounds failed
5. Only re-run the PubMed search if the follow-up question materially changes the PICO or asks for evidence outside the original search scope

If cached evidence is unavailable, say so explicitly and then decide whether a new EBM search is required.

---

## Writing principles
- Prefer precision over fluency when the two conflict
- State uncertainty explicitly
- Distinguish evidence from interpretation
- If evidence quality is weak, indirect, inconsistent, or sparse, say so clearly
- Never imply guideline-level certainty from limited data
