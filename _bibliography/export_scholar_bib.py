import os, sys, time, json, re, requests
from urllib.parse import urlencode
from slugify import slugify
from tqdm import tqdm

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
PROFILE_ID  = sys.argv[1] if len(sys.argv) > 1 else "zPJUEzsAAAAJ"
OUTFILE     = sys.argv[2] if len(sys.argv) > 2 else "annhuang.bib"

BASE = "https://serpapi.com/search.json"

def serp(params):
    params["engine"] = "google_scholar_author"
    params["api_key"] = SERPAPI_KEY
    r = requests.get(BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_all_pubs(profile_id):
    page = 0
    pubs = []
    while True:
        data = serp({"author_id": profile_id, "hl": "en", "num": "100", "start": page*100, "view_op": "list_works"})
        pubs.extend(data.get("articles", []))
        if "next" not in data.get("serpapi_pagination", {}): break
        page += 1
        time.sleep(0.5)
    return pubs

def bibtex_key(title, year):
    base = slugify(re.sub(r"[^a-zA-Z0-9 ]", "", title).lower())[:40]
    return f"{base}{year}" if year else base

def crossref_bib(doi):
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}", headers={"Accept":"application/x-bibtex"}, timeout=20)
        if r.status_code==200 and r.text.strip().startswith("@"): return r.text.strip()
    except Exception: pass
    return None

def guess_type(v):
    if v.get("publication"): return "article"
    if "Proceedings" in (v.get("publication") or "") or v.get("citation_id","").startswith("CONF"): return "inproceedings"
    if "arXiv" in (v.get("publication") or ""): return "misc"
    return "misc"

def to_bibtex(item):
    info = item.get("inline_links", {}) or {}
    title = item.get("title") or "Untitled"
    authors = item.get("authors") or []
    year = item.get("year")
    venue = item.get("publication")
    url = item.get("link")
    doi = _find_doi_in_item(item)

    # --- add these helpers near the top of the file ---
    def _iter_links_from(obj):
        """Yield URL-like strings from strings/dicts/lists arbitrarily nested 1 level."""
        if obj is None:
            return
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            # common keys that may hold URLs
            for k in ("link", "url", "pdf", "html", "serpapi_scholar_link"):
                v = obj.get(k)
                if isinstance(v, str):
                    yield v
                elif isinstance(v, dict):
                    # nested { link: ... } etc.
                    vv = v.get("link") or v.get("url")
                    if isinstance(vv, str):
                        yield vv
        elif isinstance(obj, list):
            for x in obj:
                yield from _iter_links_from(x)

    def _extract_doi(url):
        if not isinstance(url, str):
            return None
        # Match DOI in plain doi.org links or embedded in query/path
        m = re.search(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", url, re.I)
        return m.group(1) if m else None

    def _find_doi_in_item(it):
        """Search multiple fields for a DOI."""
        fields = [
            it.get("resources"),
            it.get("external_links"),
            it.get("inline_links"),
            it.get("link"),
            it.get("url"),
        ]
        for fld in fields:
            for u in _iter_links_from(fld):
                doi = _extract_doi(u)
                if doi:
                    return doi
        return None
    # --- end helpers ---


    # If DOI found → get Crossref’s official BibTeX
    if doi:
        cr = crossref_bib(doi)
        if cr:
            # add URL if missing
            if url and "url =" not in cr:
                cr = cr[:-1] + f",\n  url = {{{url}}}\n}}\n"
            return cr

    # Fallback: construct a reasonable BibTeX
    entry_type = guess_type(item)
    key = bibtex_key(title, year or "")
    author_str = " and ".join(a.get("name","") for a in authors) if authors else "Unknown"
    fields = [
        f"title = {{{title}}}",
        f"author = {{{author_str}}}",
    ]
    if year: fields.append(f"year = {{{year}}}")
    if venue: 
        if entry_type == "article":
            fields.append(f"journal = {{{venue}}}")
        elif entry_type == "inproceedings":
            fields.append(f"booktitle = {{{venue}}}")
        else:
            fields.append(f"howpublished = {{{venue}}}")
    if url: fields.append(f"url = {{{url}}}")
    if doi: fields.append(f"doi = {{{doi}}}")
    return "@{}{{{},\n  {}\n}}\n".format(entry_type, key, ",\n  ".join(fields))

def main():
    if not SERPAPI_KEY:
        print("Error: set SERPAPI_KEY environment variable.")
        sys.exit(1)

    pubs = fetch_all_pubs(PROFILE_ID)
    # Dedupe by (title, year)
    seen = set()
    uniq = []
    for p in pubs:
        t = (p.get("title","").strip().lower(), p.get("year"))
        if t not in seen:
            uniq.append(p); seen.add(t)

    bibs = []
    for p in tqdm(uniq, desc="Exporting"):
        try:
            bibs.append(to_bibtex(p))
        except Exception as e:
            # keep going
            bibs.append(f"% Failed on: {p.get('title','?')} :: {e}\n")

    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(bibs))
    print(f"Wrote {len(bibs)} entries → {OUTFILE}")

if __name__ == "__main__":
    main()
