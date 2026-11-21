"""Command line: `icer cohort`, `icer download`, `icer excerpts`, `icer all`, or `icer extract`."""

import argparse

from . import documents, excerpts, listing


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="icer", description=__doc__)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("cohort", help="parse the listing export and write the study cohort")
    for name, help_ in (
        ("download", "download each review's Recommendation, economic report and, where needed, clinical report"),
        ("excerpts", "convert PDFs to text and cut one excerpt per review"),
        ("all", "run cohort, download and excerpts in order"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--projects", nargs="+", metavar="PROJECT", help="limit to these project numbers")
    p = sub.add_parser("extract", help="run one LLM extractor on the selected pages (calls the API; not part of `all`)")
    p.add_argument("--extractor", required=True, help="extractor name, e.g. a")
    p.add_argument("--projects", nargs="+", metavar="PROJECT", help="limit to these project numbers")
    p.add_argument("--limit", type=int, help="stop after this many reviews")
    args = parser.parse_args(argv)

    if args.step in ("cohort", "all"):
        cohort = listing.run()
        if args.step == "cohort":
            return
    else:
        cohort = listing.read_cohort()
    if args.projects:
        cohort = cohort[cohort["project"].isin(args.projects)]
        if cohort.empty:
            raise SystemExit("none of the given projects are in the cohort")
    if args.step in ("download", "all"):
        documents.run(cohort)
    if args.step in ("excerpts", "all"):
        excerpts.run(cohort)
    if args.step == "extract":
        from . import extract  # imported here so the other steps need no API credentials

        if args.extractor not in extract.EXTRACTORS:
            raise SystemExit(f"unknown extractor {args.extractor!r}; known: {', '.join(extract.EXTRACTORS)}")
        extract.run(cohort.head(args.limit) if args.limit else cohort, extract.EXTRACTORS[args.extractor])


if __name__ == "__main__":
    main()
