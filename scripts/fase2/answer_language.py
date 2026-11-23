"""Share of tool-using bench answers written in Spanish (all bench queries are Spanish)."""

import json
import re
import sys

ES = {
    "el",
    "la",
    "de",
    "que",
    "en",
    "es",
    "los",
    "las",
    "del",
    "por",
    "con",
    "una",
    "un",
    "para",
    "tu",
    "su",
    "al",
    "se",
    "no",
    "más",
}
EN = {
    "the",
    "is",
    "of",
    "and",
    "to",
    "in",
    "your",
    "for",
    "with",
    "are",
    "this",
    "that",
    "you",
    "be",
    "on",
    "has",
}
for path in sys.argv[1:]:
    rows = [r for r in json.load(open(path))["rows"] if r["tool_calls"]]
    es = 0
    for r in rows:
        w = re.findall(r"[a-záéíóúñ]+", r["answer"].lower())
        es += sum(x in ES for x in w) > sum(x in EN for x in w)
    print(f"{path}: {es}/{len(rows)} answers in Spanish")
