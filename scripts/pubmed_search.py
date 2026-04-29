#!/usr/bin/env python3
"""
PubMed Clinical Literature Search Tool (for ebm-researcher skill)

3-phase pipeline: esearch → esummary (score+filter) → efetch (full abstracts)
Outputs to stdout and saves results + search log for agent consumption.

Usage:
  python3 pubmed_search.py "<query>"              # Human-readable output (default)
  python3 pubmed_search.py --json "<query>"        # JSON-only output (agent formatting)
  python3 pubmed_search.py --log "<query>"          # Print search log after results
"""
import sys
import json
import time
import re
import os
import urllib.request
import urllib.parse
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
from datetime import datetime

NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RESULTS_PATH = "/tmp/pubmed_last_results.json"
LOG_PATH = "/tmp/pubmed_search_log.json"

# ── HTTP helpers ──────────────────────────────────────────────

def make_request(url, retries=2):
    """Make HTTP request with smart retries and NCBI rate-limit compliance."""
    for attempt in range(retries + 1):
        try:
            time.sleep(0.5)  # NCBI rate limit: ≥0.34s, we use 0.5s
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        except HTTPError as e:
            if e.code in [429, 503, 500, 502] and attempt < retries:
                time.sleep((attempt + 1) * 2)
                continue
            raise e
        except Exception as e:
            if attempt < retries:
                time.sleep((attempt + 1) * 2)
                continue
            raise e
    return None

# ── XML text extraction ──────────────────────────────────────

def extract_text(elem):
    """Recursively extract all text from an XML element and its children.
    Handles <i>, <sup>, <sub>, <b>, <inline-formula>, etc. in PubMed XML."""
    if elem is None:
        return ""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(extract_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)

# ── NCBI E-utilities wrappers ────────────────────────────────

def esearch(query, retmax=50):
    """Phase 1: Get PMIDs matching the query."""
    encoded_query = urllib.parse.quote(query)
    url = f"{NCBI_BASE_URL}/esearch.fcgi?db=pubmed&term={encoded_query}&retmax={retmax}&retmode=json"
    try:
        response_bytes = make_request(url)
        if response_bytes:
            data = json.loads(response_bytes.decode('utf-8'))
            return data.get('esearchresult', {}).get('idlist', [])
        return []
    except Exception as e:
        print(f"esearch failed: {e}", file=sys.stderr)
        return []

def esummary(pmids):
    """Phase 2: Get metadata (title, journal, date, pubtype) for filtering."""
    if not pmids:
        return {}
    pmid_str = ",".join(pmids)
    url = f"{NCBI_BASE_URL}/esummary.fcgi?db=pubmed&id={pmid_str}&retmode=json"
    try:
        response_bytes = make_request(url)
        if response_bytes:
            data = json.loads(response_bytes.decode('utf-8'))
            return data.get('result', {})
        return {}
    except Exception as e:
        print(f"esummary failed: {e}", file=sys.stderr)
        return {}

def efetch(pmids):
    """Phase 3: Fetch full abstracts via XML parsing."""
    if not pmids:
        return []
    pmid_str = ",".join(pmids)
    url = f"{NCBI_BASE_URL}/efetch.fcgi?db=pubmed&id={pmid_str}&retmode=xml"
    articles = []
    try:
        response_bytes = make_request(url)
        if not response_bytes:
            return []

        # NOTE: Do NOT add .replace('&', '&amp;') here.
        # PubMed efetch returns valid XML; double-escaping breaks entities.
        xml_content = response_bytes.decode('utf-8')

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            print(f"XML Parsing error in efetch: {e}", file=sys.stderr)
            return []

        for article in root.findall('.//PubmedArticle'):
            # PMID
            pmid_elem = article.find('.//PMID')
            pmid = pmid_elem.text if pmid_elem is not None else 'Unknown'

            # Title (recursive text extraction for <i>, <sup>, etc.)
            title_elem = article.find('.//ArticleTitle')
            title = extract_text(title_elem).strip() if title_elem is not None else 'No Title'

            # Journal
            journal_elem = article.find('.//Journal/Title')
            journal = extract_text(journal_elem).strip() if journal_elem is not None else 'Unknown Journal'

            # Date
            pub_date_elem = article.find('.//PubDate')
            date_str = "Unknown Date"
            if pub_date_elem is not None:
                parts = []
                for p in ['Year', 'Month', 'Day']:
                    e = pub_date_elem.find(p)
                    if e is not None and e.text:
                        parts.append(e.text)
                if parts:
                    date_str = "-".join(parts)

            # Abstract (handle structured abstracts with multiple AbstractText)
            abstract_texts = []
            for abs_elem in article.findall('.//AbstractText'):
                label = abs_elem.get('Label', '')
                text = extract_text(abs_elem).strip()
                if text:
                    if label:
                        abstract_texts.append(f"{label}: {text}")
                    else:
                        abstract_texts.append(text)
            abstract = " ".join(abstract_texts) if abstract_texts else "No abstract available."

            # Publication types (for evidence level reporting)
            pub_types = []
            for pt_elem in article.findall('.//PublicationType'):
                if pt_elem.text:
                    pub_types.append(pt_elem.text)

            articles.append({
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "date": date_str,
                "abstract": abstract,
                "pub_types": pub_types,
            })

        return articles
    except Exception as e:
        print(f"efetch failed: {e}", file=sys.stderr)
        return []

# ── Scoring & filtering ──────────────────────────────────────

# PublicationType values from PubMed (more reliable than title keywords)
_PUBTYPE_SCORES = {
    "meta-analysis": 5,
    "systematic review": 5,
    "randomized controlled trial": 4,
    "pragmatic clinical trial": 4,
    "clinical trial, phase iii": 4,
    "clinical trial, phase ii": 3,
    "clinical trial, phase i": 3,
    "clinical trial": 4,
    "controlled clinical trial": 4,
    "observational study": 3,
    "cohort study": 3,
    "multicenter study": 3,
    "comparative study": 3,
    "case-control study": 3,
    "cross-sectional study": 2,
    "case reports": 1,
    "editorial": 1,
    "letter": 1,
    "comment": 1,
    "review": 3,
}

# Title keyword fallback scoring (when pubtype doesn't match)
_TITLE_SCORE_PATTERNS = [
    (5, ["systematic review", "meta-analysis", "meta analysis", "cochrane"]),
    (4, ["randomized", "randomised", "rct", "double-blind", "placebo-controlled"]),
    (3, ["cohort", "case-control", "prospective", "retrospective",
         "clinical trial", "clinical study", "observational"]),
    (2, ["patient", "therapy", "treatment", "diagnosis", "outcome", "efficacy", "safety"]),
    (1, ["case report", "case series", "editorial", "letter", "commentary"]),
]

TOP_JOURNALS = [
    "new england journal of medicine", "the lancet", "jama",
    "nature medicine", "bmj", "nature", "science", "cell",
    "annals of internal medicine", "circulation", "the bmj",
    "jama internal medicine", "lancet respiratory medicine",
    "european heart journal", "jama cardiology", "gastroenterology",
    "hepatology", "the lancet gastroenterology & hepatology",
]

def score_study_design(title, pub_types=None):
    """Score article by evidence level. Uses PublicationType when available, falls back to title."""
    # Primary: use PubMed PublicationType (most reliable)
    if pub_types:
        for pt in pub_types:
            pt_lower = pt.lower()
            if pt_lower in _PUBTYPE_SCORES:
                return _PUBTYPE_SCORES[pt_lower]
            # Partial match for compound types
            for key, score in _PUBTYPE_SCORES.items():
                if key in pt_lower or pt_lower in key:
                    return score

    # Fallback: title keyword matching
    title_lower = title.lower()
    for score, keywords in _TITLE_SCORE_PATTERNS:
        if any(kw in title_lower for kw in keywords):
            return score
    return 2  # Default: moderate relevance

def get_pub_year(pubdate_str):
    """Extract year from pubdate string like '2024 Jan 15' or '2024'."""
    for token in pubdate_str.split():
        if token.isdigit() and len(token) == 4:
            return int(token)
    return 0

def filter_articles(summary_data):
    """Apply tiered filtering: 3yr → 10yr → all, sorted by evidence level."""
    current_year = datetime.now().year
    all_articles = []

    for uid, article_data in summary_data.items():
        if uid == 'uids':
            continue
        title = article_data.get('title', '')
        journal = article_data.get('fulljournalname', '').lower()
        pubdate = article_data.get('pubdate', '')
        pub_year = get_pub_year(pubdate)

        # Extract publication types from esummary
        pub_types = []
        pubtype_list = article_data.get('pubtype', [])
        if isinstance(pubtype_list, list):
            pub_types = pubtype_list

        design_score = score_study_design(title, pub_types)
        is_top_journal = any(j in journal for j in TOP_JOURNALS)
        if is_top_journal:
            design_score += 1

        all_articles.append({
            'uid': uid,
            'title': title,
            'pub_year': pub_year,
            'design_score': design_score,
            'pub_types': pub_types,
            'journal': article_data.get('fulljournalname', ''),
        })

    if not all_articles:
        return [], []

    # Tier 1: Recent 3 years
    tier1 = [a for a in all_articles if a['pub_year'] >= current_year - 3]
    if len(tier1) >= 2:
        tier1.sort(key=lambda a: a['design_score'], reverse=True)
        selected = tier1[:5]
        return [a['uid'] for a in selected], selected

    # Tier 2: Recent 10 years
    tier2 = [a for a in all_articles if a['pub_year'] >= current_year - 10]
    if len(tier2) >= 2:
        tier2.sort(key=lambda a: a['design_score'], reverse=True)
        selected = tier2[:5]
        return [a['uid'] for a in selected], selected

    # Tier 3: All time
    all_articles.sort(key=lambda a: a['design_score'], reverse=True)
    selected = all_articles[:5]
    return [a['uid'] for a in selected], selected

# ── Query widening ────────────────────────────────────────────

def strip_all_field_tags(query):
    """Remove ALL PubMed field tags [xxx] from the query for broadening."""
    return re.sub(r'\[[\w\s\-]+\]', '', query).strip()

def strip_date_and_titab(query):
    """Remove only [tiab] and date-related tags (the gentlest broadening)."""
    q = re.sub(r'\[tiab\]', '', query, flags=re.IGNORECASE)
    q = re.sub(r'\[Date\s*-\s*Publication\]', '', q, flags=re.IGNORECASE)
    return q.strip()

# ── Search log ────────────────────────────────────────────────

class SearchLog:
    """Track search rounds for the agent's 3-strike report."""
    def __init__(self):
        self.rounds = []
        self.original_query = ""

    def add_round(self, query, pmid_count, tier_info=None, note=""):
        self.rounds.append({
            "query": query,
            "pmid_count": pmid_count,
            "tier_info": tier_info,
            "note": note,
        })

    def save(self, path=LOG_PATH):
        log = {
            "original_query": self.original_query,
            "rounds": self.rounds,
            "timestamp": datetime.now().isoformat(),
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

# ── Main search pipeline ─────────────────────────────────────

def smart_search(query, json_mode=False):
    """Execute the full 3-phase search with auto-widening on zero results."""
    log = SearchLog()
    log.original_query = query

    def emit(msg):
        if not json_mode:
            print(msg, file=sys.stderr)

    # ── Round 1: Original query ──
    emit(f"🔍 [Phase 1] Original query: {query}")
    pmids = esearch(query, retmax=50)
    emit(f"ℹ️  Found {len(pmids)} PMIDs")

    # ── Round 2 (auto-widen): Strip field tags if zero results ──
    if len(pmids) == 0:
        widened = strip_all_field_tags(query)
        if widened != query:
            emit(f"🔄 [Auto-widen] Stripping field tags → {widened}")
            pmids = esearch(widened, retmax=50)
            emit(f"ℹ️  Found {len(pmids)} PMIDs")
            log.add_round(widened, len(pmids), note="auto-widen: stripped all field tags")
    else:
        log.add_round(query, len(pmids), note="original query")

    if len(pmids) == 0:
        log.add_round(query, 0, note="zero results after widening")
        log.save()
        if json_mode:
            print(json.dumps({"articles": [], "log": log.rounds}, ensure_ascii=False))
        else:
            print("❌ No articles found after widening.")
        return

    # ── Phase 2: Score, filter, select top PMIDs ──
    look_at = min(len(pmids), 20)
    test_pmids = pmids[:look_at]

    emit(f"📖 [Phase 2] Scoring {look_at} articles by evidence level...")
    summary_data = esummary(test_pmids)
    good_pmids, selected_meta = filter_articles(summary_data)

    # Record tier info for log
    if selected_meta:
        tier_desc = f"{'3yr' if selected_meta[0]['pub_year'] >= datetime.now().year - 3 else '10yr' if selected_meta[0]['pub_year'] >= datetime.now().year - 10 else 'all'}"
        log.rounds[-1]["tier_info"] = tier_desc
        log.rounds[-1]["selected_scores"] = [a['design_score'] for a in selected_meta]

    emit(f"✨ Selected {len(good_pmids)} high-evidence articles")

    # ── Phase 3: Fetch full abstracts ──
    final_articles = efetch(good_pmids)

    if not final_articles:
        log.save()
        if json_mode:
            print(json.dumps({"articles": [], "log": log.rounds}, ensure_ascii=False))
        else:
            print("❌ Could not fetch article details.")
        return

    # ── Save results for follow-up questions ──
    with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_articles, f, ensure_ascii=False, indent=2)

    log.add_round(query, len(final_articles), note=f"fetched {len(final_articles)} full abstracts")
    log.save()

    # ── Output ──
    if json_mode:
        output = {
            "articles": final_articles,
            "search_log": {
                "original_query": log.original_query,
                "rounds": log.rounds,
                "results_path": RESULTS_PATH,
                "log_path": LOG_PATH,
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n✅ Done. Retrieved {len(final_articles)} articles:\n")
        print(f"(Full abstracts saved to {RESULTS_PATH})")
        print(f"(Search log saved to {LOG_PATH})\n")
        for a in final_articles:
            pt_str = f" [{', '.join(a.get('pub_types', []))}]" if a.get('pub_types') else ""
            print(f"**{a['journal']}** ({a['date']}){pt_str}")
            print(f"{a['title']}")
            print(f"🔗 https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/")
            print(f"📄 Abstract:")
            print(f"  {a['abstract']}\n")

# ── CLI entry point ───────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: pubmed_search.py [--json] [--log] <query>")
        sys.exit(1)

    # Parse flags
    args = sys.argv[1:]
    json_mode = "--json" in args
    log_mode = "--log" in args
    args = [a for a in args if a not in ("--json", "--log")]

    # Defensive: strip hallucinated flags from AI models
    raw_args = " ".join(args)
    sanitized = raw_args
    sanitized = re.sub(r'--query\s+', '', sanitized)
    sanitized = re.sub(r'--max-results\s+\d+', '', sanitized)
    sanitized = re.sub(r'--limit\s+\d+', '', sanitized)
    sanitized = re.sub(r'--retmax\s+\d+', '', sanitized)
    sanitized = re.sub(r'--sort\s+\S+', '', sanitized)
    sanitized = re.sub(r'--format\s+\S+', '', sanitized)
    sanitized = sanitized.strip().strip('"').strip("'").strip()

    if sanitized != raw_args.strip():
        print(f"⚠️  [Auto-fix] Stripped invalid flags.", file=sys.stderr)
        print(f"  Input:   {raw_args}", file=sys.stderr)
        print(f"  Cleaned: {sanitized}", file=sys.stderr)

    if not sanitized:
        print("❌ Query is empty after cleanup.")
        sys.exit(1)

    smart_search(sanitized, json_mode=json_mode)

    # --log: also dump the search log to stdout after results
    if log_mode and os.path.exists(LOG_PATH):
        print("\n--- Search Log ---")
        with open(LOG_PATH, 'r') as f:
            print(f.read())
