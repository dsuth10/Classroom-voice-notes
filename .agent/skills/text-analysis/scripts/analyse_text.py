#!/usr/bin/env python3
"""
Text Analysis Script — Readability Assessment Tool
Calculates readability scores and validates text against target reading levels.

Usage:
  python analyse_text.py <file> [--level L1|L2|L3] [--json]
  echo "Some text" | python analyse_text.py [--level L1]
"""

import sys
import argparse
import json

try:
    import textstat
except ImportError:
    print("ERROR: textstat not installed. Run: pip install textstat")
    sys.exit(1)

# Target ranges per reading level
LEVEL_TARGETS = {
    "L1": {
        "label": "Level 1 — 12–13 years (approx. Grade 7–8)",
        "fk_min": 6.5, "fk_max": 8.5,
        "flesch_min": 55, "flesch_max": 72,
    },
    "L2": {
        "label": "Level 2 — 10–11 years (approx. Grade 5–6)",
        "fk_min": 4.5, "fk_max": 6.5,
        "flesch_min": 68, "flesch_max": 82,
    },
    "L3": {
        "label": "Level 3 — 8–9 years (approx. Grade 3–4)",
        "fk_min": 2.5, "fk_max": 4.5,
        "flesch_min": 78, "flesch_max": 92,
    },
}


def analyse(text: str, target_level: str = None) -> dict:
    word_count = textstat.lexicon_count(text, removepunct=True)
    sentence_count = textstat.sentence_count(text)

    scores = {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": round(word_count / max(sentence_count, 1), 1),
        "flesch_reading_ease": round(textstat.flesch_reading_ease(text), 1),
        "flesch_kincaid_grade": round(textstat.flesch_kincaid_grade(text), 1),
        "smog_index": round(textstat.smog_index(text), 1),
        "automated_readability_index": round(textstat.automated_readability_index(text), 1),
        "coleman_liau_index": round(textstat.coleman_liau_index(text), 1),
        "gunning_fog": round(textstat.gunning_fog(text), 1),
    }

    if target_level and target_level in LEVEL_TARGETS:
        t = LEVEL_TARGETS[target_level]
        fk = scores["flesch_kincaid_grade"]
        fe = scores["flesch_reading_ease"]

        fk_pass = t["fk_min"] <= fk <= t["fk_max"]
        fe_pass = t["flesch_min"] <= fe <= t["flesch_max"]

        scores["target_level"] = target_level
        scores["target_label"] = t["label"]
        scores["fk_grade_pass"] = fk_pass
        scores["flesch_pass"] = fe_pass
        scores["overall_pass"] = fk_pass and fe_pass
        scores["suggestions"] = []

        if not fk_pass:
            if fk < t["fk_min"]:
                scores["suggestions"].append("F-K Grade too low: increase sentence length and vocabulary complexity.")
            else:
                scores["suggestions"].append("F-K Grade too high: shorten sentences and simplify vocabulary.")

        if not fe_pass:
            if fe > t["flesch_max"]:
                scores["suggestions"].append("Flesch score too high (too easy): add more complex sentence structures.")
            else:
                scores["suggestions"].append("Flesch score too low (too hard): use shorter words and simpler sentences.")

    return scores


def format_report(s: dict) -> str:
    sep = "=" * 52
    lines = [
        sep,
        "  READABILITY ANALYSIS REPORT",
        sep,
        f"  Word Count:            {s['word_count']}",
        f"  Sentence Count:        {s['sentence_count']}",
        f"  Avg Sentence Length:   {s['avg_sentence_length']} words",
        "",
        "  Scores",
        "  ------",
        f"  Flesch Reading Ease:   {s['flesch_reading_ease']}  (higher = easier)",
        f"  Flesch-Kincaid Grade:  {s['flesch_kincaid_grade']}  (US grade equivalent)",
        f"  SMOG Index:            {s['smog_index']}",
        f"  ARI:                   {s['automated_readability_index']}",
        f"  Coleman-Liau:          {s['coleman_liau_index']}",
        f"  Gunning Fog:           {s['gunning_fog']}",
    ]

    if "target_level" in s:
        p = lambda v: "PASS" if v else "FAIL"
        lines += [
            "",
            f"  Target: {s['target_label']}",
            "  " + "-" * 48,
            f"  Flesch-Kincaid Grade:  {p(s['fk_grade_pass'])}",
            f"  Flesch Reading Ease:   {p(s['flesch_pass'])}",
            f"  Overall Result:        {p(s['overall_pass'])}",
        ]
        for suggestion in s.get("suggestions", []):
            lines.append(f"  >> {suggestion}")

    lines.append(sep)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyse text readability.")
    parser.add_argument("file", nargs="?", help="Path to a .txt file (omit to use stdin)")
    parser.add_argument("--level", choices=["L1", "L2", "L3"], help="Validate against a target reading level")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a report")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("ERROR: No text provided.")
        sys.exit(1)

    if textstat.lexicon_count(text, removepunct=True) < 50:
        print("WARNING: Text is very short. Scores may be unreliable below 100 words.")

    scores = analyse(text, args.level)

    if args.json:
        print(json.dumps(scores, indent=2))
    else:
        print(format_report(scores))


if __name__ == "__main__":
    main()
