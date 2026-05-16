#!/usr/bin/env python3
"""
Search OpenAlex for scientific papers and return structured results.

Keyword search:
  python mmx_search_papers.py "query" [--limit N] [--year-from YYYY] [--oa-only]

Citation/reference traversal (stdin = DOI or OpenAlex ID):
  python mmx_search_papers.py <doi-or-id> --cites   # papers that cite this work
  python mmx_search_papers.py <doi-or-id> --refs    # papers this work references

Chaining example:
  echo "W2741809807" | mmxsearchpapers --cites --json | mmxgetpaper 1 | ...
  echo "10.1016/j.tics.2022.02.009" | mmxsearchpapers --refs --limit 20
"""
import argparse
import json as jsonlib
import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    import pyalex
    from pyalex import Works
except ImportError:
    print("pyalex not installed. Run: pip install pyalex", file=sys.stderr)
    sys.exit(1)

# OpenAlex polite pool: identify yourself via email (no key needed)
email = os.getenv("OPENALEX_EMAIL", "")
if email:
    pyalex.config.email = email


def resolve_id(id_or_doi):
    """Return the OpenAlex ID for a DOI or OpenAlex ID string."""
    id_or_doi = id_or_doi.strip()
    if id_or_doi.startswith("W") and id_or_doi[1:].isdigit():
        return id_or_doi
    # treat as DOI
    doi = id_or_doi.replace("https://doi.org/", "")
    results = Works().filter(doi=doi).get(per_page=1)
    if not results:
        print(f"ERROR: could not resolve DOI: {doi}", file=sys.stderr)
        sys.exit(1)
    return results[0]["id"].split("/")[-1]  # e.g. W2741809807


def work_to_dict(work):
    authors = ", ".join(
        a["author"].get("display_name", "?")
        for a in (work.get("authorships") or [])[:5]
    )
    if len(work.get("authorships") or []) > 5:
        authors += " et al."

    oa_url = None
    oa = work.get("open_access") or {}
    if oa.get("oa_url"):
        oa_url = oa["oa_url"]
    elif oa.get("oa_status") == "gold":
        oa_url = work.get("doi")

    return {
        "title": work.get("display_name", ""),
        "authors": authors,
        "year": work.get("publication_year"),
        "journal": ((work.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
        "doi": work.get("doi", ""),
        "oa_url": oa_url,
        "cited_by": work.get("cited_by_count", 0),
        "abstract": work.get("abstract", "") or "",
        "openalex_id": work.get("id", ""),
    }


def search(query, limit=10, year_from=None, open_access_only=False):
    q = Works().search(query)
    if year_from:
        q = q.filter(publication_year=f">{year_from - 1}")
    if open_access_only:
        q = q.filter(is_oa=True)
    q = q.sort(relevance_score="desc")
    return [work_to_dict(w) for w in q.get(per_page=limit)]


def search_cites(openalex_id, limit=10, year_from=None, open_access_only=False):
    """Papers that cite the given work."""
    q = Works().filter(cites=openalex_id)
    if year_from:
        q = q.filter(publication_year=f">{year_from - 1}")
    if open_access_only:
        q = q.filter(is_oa=True)
    q = q.sort(cited_by_count="desc")
    return [work_to_dict(w) for w in q.get(per_page=limit)]


def search_refs(openalex_id, limit=10, open_access_only=False):
    """Papers referenced by the given work."""
    work = Works()[f"https://openalex.org/{openalex_id}"]
    ref_ids = (work.get("referenced_works") or [])[:limit * 3]  # over-fetch, filter below
    if not ref_ids:
        return []
    # Batch fetch by ID
    id_filter = "|".join(r.split("/")[-1] for r in ref_ids)
    q = Works().filter(openalex_id=id_filter)
    if open_access_only:
        q = q.filter(is_oa=True)
    results = [work_to_dict(w) for w in q.get(per_page=min(limit, 200))]
    return sorted(results, key=lambda r: r["cited_by"], reverse=True)[:limit]


def format_results(results, header=""):
    lines = []
    if header:
        lines.append(f"# {header}\n")
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r['title']} ({r['year']})")
        lines.append(f"**Authors:** {r['authors']}")
        if r["journal"]:
            lines.append(f"**Journal:** {r['journal']}")
        lines.append(f"**Cited by:** {r['cited_by']}")
        if r["doi"]:
            lines.append(f"**DOI:** {r['doi']}")
        if r["oa_url"]:
            lines.append(f"**Open access PDF:** {r['oa_url']}")
        if r["abstract"]:
            abstract = r["abstract"][:400] + ("…" if len(r["abstract"]) > 400 else "")
            lines.append(f"**Abstract:** {abstract}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Search OpenAlex for papers")
    parser.add_argument("query", help="Search query, DOI, or OpenAlex ID")
    parser.add_argument("--limit", type=int, default=10, help="Number of results (default: 10)")
    parser.add_argument("--year-from", type=int, help="Filter: published from this year")
    parser.add_argument("--oa-only", action="store_true", help="Open access papers only")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--cites", action="store_true",
                        help="stdin is a DOI/OpenAlex ID; return papers that cite it")
    parser.add_argument("--refs", action="store_true",
                        help="stdin is a DOI/OpenAlex ID; return its reference list")
    args = parser.parse_args()

    if args.cites and args.refs:
        print("ERROR: --cites and --refs are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if args.cites or args.refs:
        oa_id = resolve_id(args.query)
        if args.cites:
            results = search_cites(oa_id, limit=args.limit, year_from=args.year_from,
                                   open_access_only=args.oa_only)
            header = f"Papers citing {args.query.strip()}"
        else:
            results = search_refs(oa_id, limit=args.limit, open_access_only=args.oa_only)
            header = f"References of {args.query.strip()}"
    else:
        results = search(args.query, limit=args.limit, year_from=args.year_from,
                         open_access_only=args.oa_only)
        header = f"OpenAlex results for: '{args.query}'"

    if args.json:
        print(jsonlib.dumps(results, indent=2))
    else:
        print(format_results(results, header=header))


if __name__ == "__main__":
    main()
