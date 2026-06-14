#!/usr/bin/env python3
"""
Leveled Text Creator — Automatic Readability Calibration Tool
Calibrates and generates reading texts mapped to Australian Curriculum Year levels.
"""

import os
import sys
import re
import json
import argparse
import subprocess
import urllib.request
import urllib.error

# Ensure textstat is installed
try:
    import textstat
except ImportError:
    print("ERROR: The 'textstat' package is not installed. Please run: pip install textstat")
    sys.exit(1)

# Australian Curriculum Year levels mapped to target readability scores and guidelines
YEAR_LEVEL_TARGETS = {
    1: {
        "age_range": "6–7 yrs",
        "fk_min": 0.5, "fk_max": 1.8,
        "fre_min": 90.0, "fre_max": 100.0,
        "target_words": "50–100",
        "avg_sentence_len": "5–8 words",
        "guideline": "Extremely simple sentences, active voice, basic vocabulary with immediate parenthetical explanations."
    },
    2: {
        "age_range": "7–8 yrs",
        "fk_min": 1.8, "fk_max": 2.8,
        "fre_min": 85.0, "fre_max": 95.0,
        "target_words": "100–150",
        "avg_sentence_len": "8–10 words",
        "guideline": "Short sentences, simple transitions, clear logical steps."
    },
    3: {
        "age_range": "8–9 yrs",
        "fk_min": 2.8, "fk_max": 3.8,
        "fre_min": 80.0, "fre_max": 90.0,
        "target_words": "150–250",
        "avg_sentence_len": "10–12 words",
        "guideline": "Coordinate clauses, direct sentence structure, clear sequence of events."
    },
    4: {
        "age_range": "9–10 yrs",
        "fk_min": 3.8, "fk_max": 4.8,
        "fre_min": 75.0, "fre_max": 85.0,
        "target_words": "200–300",
        "avg_sentence_len": "12–14 words",
        "guideline": "Mild sentence variation, direct explanations of concepts."
    },
    5: {
        "age_range": "10–11 yrs",
        "fk_min": 4.8, "fk_max": 5.8,
        "fre_min": 70.0, "fre_max": 80.0,
        "target_words": "250–350",
        "avg_sentence_len": "14–16 words",
        "guideline": "Varied paragraph lengths, standard complex sentences, moderate descriptive detail."
    },
    6: {
        "age_range": "11–12 yrs",
        "fk_min": 5.8, "fk_max": 6.8,
        "fre_min": 65.0, "fre_max": 75.0,
        "target_words": "300–400",
        "avg_sentence_len": "15–18 words",
        "guideline": "Standard narrative and informative structures, compound-complex sentences allowed."
    },
    7: {
        "age_range": "12–13 yrs",
        "fk_min": 6.8, "fk_max": 7.8,
        "fre_min": 60.0, "fre_max": 70.0,
        "target_words": "350–450",
        "avg_sentence_len": "16–20 words",
        "guideline": "Inference-heavy vocabulary, multi-layered explanations."
    },
    8: {
        "age_range": "13–14 yrs",
        "fk_min": 7.8, "fk_max": 8.8,
        "fre_min": 55.0, "fre_max": 65.0,
        "target_words": "400–500",
        "avg_sentence_len": "18–22 words",
        "guideline": "Deeper analysis, formal academic sentence structures."
    },
    9: {
        "age_range": "14–15 yrs",
        "fk_min": 8.8, "fk_max": 9.8,
        "fre_min": 50.0, "fre_max": 60.0,
        "target_words": "450–550",
        "avg_sentence_len": "18–24 words",
        "guideline": "Complex argument development, dense information packaging."
    },
    10: {
        "age_range": "15–16 yrs",
        "fk_min": 9.8, "fk_max": 11.0,
        "fre_min": 40.0, "fre_max": 55.0,
        "target_words": "500–600",
        "avg_sentence_len": "18–25 words",
        "guideline": "Advanced synthesising of concepts, sophisticated language structures."
    }
}


def analyse_text_readability(text: str, year_level: int) -> dict:
    """Calculates readability metrics using textstat and determines pass/fail status."""
    word_count = textstat.lexicon_count(text, removepunct=True)
    sentence_count = textstat.sentence_count(text)
    avg_sentence_length = word_count / max(sentence_count, 1)

    fk_grade = round(textstat.flesch_kincaid_grade(text), 1)
    fre_ease = round(textstat.flesch_reading_ease(text), 1)

    t = YEAR_LEVEL_TARGETS[year_level]
    fk_pass = t["fk_min"] <= fk_grade <= t["fk_max"]
    fre_pass = t["fre_min"] <= fre_ease <= t["fre_max"]

    suggestions = []
    if not fk_pass:
        if fk_grade < t["fk_min"]:
            suggestions.append(f"Flesch-Kincaid Grade ({fk_grade}) is too low (target: {t['fk_min']}-{t['fk_max']}). Try using slightly longer sentences and more descriptive phrasing.")
        else:
            suggestions.append(f"Flesch-Kincaid Grade ({fk_grade}) is too high (target: {t['fk_min']}-{t['fk_max']}). Break complex sentences into separate, simple sentences. Prefer active voice and direct phrasing.")

    if not fre_pass:
        if fre_ease > t["fre_max"]:
            suggestions.append(f"Flesch Reading Ease ({fre_ease}) indicates text is too easy (target: {t['fre_min']}-{t['fre_max']}). Integrate a few compound clauses.")
        else:
            suggestions.append(f"Flesch Reading Ease ({fre_ease}) indicates text is too difficult (target: {t['fre_min']}-{t['fre_max']}). Replace complex grammatical constructs with direct structures.")

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": round(avg_sentence_length, 1),
        "flesch_kincaid_grade": fk_grade,
        "flesch_reading_ease": fre_ease,
        "fk_pass": fk_pass,
        "fre_pass": fre_pass,
        "overall_pass": fk_pass and fre_pass,
        "suggestions": suggestions
    }


def query_gemini_api(api_key: str, prompt: str) -> str:
    """Queries the Gemini API using urllib to generate or refine text."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode("utf-8")
            res_json = json.loads(res_data)
            return res_json["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.URLError as e:
        print(f"API Connection Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error calling Gemini API: {e}")
        sys.exit(1)


def extract_vocabulary_definitions(text: str) -> dict:
    """Finds all defined terms in the format: term (definition) inside the text."""
    # Find words followed by parenthetical descriptions
    matches = re.findall(r'(\b[A-Za-z0-9\s\-]{3,30})\s*\(([^)]+)\)', text)
    vocab = {}
    for term, definition in matches:
        cleaned_term = term.strip().capitalize()
        cleaned_definition = definition.strip()
        # Avoid capturing general parenthetical side-notes
        if len(cleaned_definition.split()) <= 15:
            vocab[cleaned_term] = cleaned_definition
    return vocab


def make_docx(title: str, year_level: int, text: str, word_count: int, vocabulary: dict, output_path: str):
    """Triggers the create_docx.js Node.js script to assemble the Word document."""
    # Write temp JSON file for the Node script
    temp_json_path = output_path + ".temp.json"
    payload = {
        "title": title,
        "year_level": year_level,
        "text": text,
        "word_count": word_count,
        "vocabulary": vocabulary
    }
    with open(temp_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # Resolve paths
    script_dir = os.path.dirname(os.path.realpath(__file__))
    node_script = os.path.join(script_dir, "create_docx.js")

    print("Compiling Word document using node script...")
    try:
        result = subprocess.run(
            ["node", node_script, temp_json_path, output_path],
            capture_output=True,
            text=True,
            check=True
        )
        print(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to run Node.js docx compiler: {e.stderr}")
    finally:
        if os.path.exists(temp_json_path):
            os.remove(temp_json_path)


def run_refinement_loop(api_key: str, topic: str, year_level: int, length: int) -> tuple:
    """Executes the automatic generation and iterative refinement loop using the Gemini API."""
    target = YEAR_LEVEL_TARGETS[year_level]
    
    # System Instructions / Guidelines for text generation
    base_instructions = (
        f"You are an educational text designer crafting reading passages for Australian Curriculum primary and secondary school students.\n"
        f"Generate a reading passage about the topic: '{topic}'.\n"
        f"Target Year Level: Year {year_level} (Student Age: {target['age_range']}).\n"
        f"Target Length: Approximately {length} words.\n\n"
        f"CRITICAL GUIDELINES FOR TEXT SIMPLIFICATION AND WRITING:\n"
        f"1. Retain Technical Terminology: Keep all core, topic-specific vocabulary intact (e.g. 'photosynthesis', 'atmosphere'). Do not remove them.\n"
        f"2. Explain Abstract Terms Inline: Right after introducing a technical or abstract term, define it briefly in parentheses, e.g. 'evaporation (when water changes from a liquid to a gas)'.\n"
        f"3. Sentence Syntax: Opt for shortening sentences. Avoid complex multi-clause structures and passive voice. Use simple sentences instead of complex ones to control difficulty.\n"
        f"4. Logical Rigour: Retain all step-by-step concepts of the topic. Simply explain the steps using clear, direct language rather than omitting content.\n"
        f"5. Title: End the response with the text. Start the text with a clear, engaging title."
    )

    history = []
    current_prompt = base_instructions
    iteration = 1
    max_iterations = 5

    print(f"\nStarting automatic generation for Year {year_level} (Topic: '{topic}')...")
    
    while iteration <= max_iterations:
        print(f"--- Iteration {iteration} ---")
        print("Calling Gemini API...")
        draft_text = query_gemini_api(api_key, current_prompt)
        
        # Strip potential markdown code fence wrappers from LLM output
        draft_text = re.sub(r"^```markdown\s*|^```\s*", "", draft_text)
        draft_text = re.sub(r"\s*```$", "", draft_text)
        draft_text = draft_text.strip()
        
        # Extract title and clean up
        lines = draft_text.split('\n')
        title = "Reading Passage"
        body_lines = []
        
        # Look for title in first 3 lines
        title_found = False
        for line in lines[:3]:
            line_clean = line.strip().replace('#', '').strip()
            if line_clean and not title_found:
                title = line_clean
                title_found = True
            elif line_clean:
                body_lines.append(line.strip())
        body_lines.extend([line.strip() for line in lines[3:]])
        
        clean_body = "\n".join(body_lines).strip()
        
        # Analyze draft
        metrics = analyse_text_readability(clean_body, year_level)
        history.append({
            "iteration": iteration,
            "text": clean_body,
            "title": title,
            "metrics": metrics
        })
        
        print(f"Draft Stats: Words={metrics['word_count']}, F-K Grade={metrics['flesch_kincaid_grade']} (Target: {target['fk_min']}-{target['fk_max']}), Flesch Ease={metrics['flesch_reading_ease']} (Target: {target['fre_min']}-{target['fre_max']})")
        
        if metrics["overall_pass"]:
            print(f"SUCCESS: Readability criteria met on iteration {iteration}!")
            return title, clean_body, history
        
        # Construct refinement prompt based on analyzer feedback
        feedback_lines = [
            f"Your previous draft did not meet the readability standards for Year {year_level} students.",
            "Here are the current text statistics:",
            f"- Word Count: {metrics['word_count']} words (Target: {target['target_words']})",
            f"- Flesch-Kincaid Grade: {metrics['flesch_kincaid_grade']} (Target: {target['fk_min']} to {target['fk_max']})",
            f"- Flesch Reading Ease: {metrics['flesch_reading_ease']} (Target: {target['fre_min']} to {target['fre_max']})",
            f"- Avg Sentence Length: {metrics['avg_sentence_length']} words (Target: {target['avg_sentence_len']})",
            "\nAnalyzer Feedback & Suggestions:"
        ]
        for sug in metrics["suggestions"]:
            feedback_lines.append(f">> {sug}")
            
        feedback_lines.extend([
            "\nPlease rewrite the text to align with these stats. Remember:",
            "- DO NOT remove topic-specific technical vocabulary.",
            "- Explain abstract terms inline using parentheses, e.g. term (brief explanation).",
            "- If the text is too complex, split long sentences into two or more short, active sentences.",
            "- If the text is too simple, link short sentences together using simple conjunctions (e.g. 'and', 'but').",
            "- Maintain all sequential steps and content knowledge of the topic.",
            "\nHere is the current draft to revise:",
            "====================",
            clean_body,
            "===================="
        ])
        
        current_prompt = "\n".join(feedback_lines)
        iteration += 1
        
    print("\nWARNING: Reached maximum iterations without meeting exact readability ranges. Returning best draft.")
    # Return the draft closest to F-K Grade midpoint
    midpoint = (target["fk_min"] + target["fk_max"]) / 2
    best_draft = min(history, key=lambda x: abs(x["metrics"]["flesch_kincaid_grade"] - midpoint))
    return best_draft["title"], best_draft["text"], history


def format_report_logs(topic: str, year_level: int, target: dict, history: list) -> str:
    """Assembles a detailed text file detailing the iterative refinement steps and final results."""
    lines = [
        "=" * 60,
        "          LEVELED TEXT CREATOR AUDIT REPORT",
        "=" * 60,
        f"Topic:                 {topic}",
        f"Target Year Level:     Year {year_level} (Student Age: {target['age_range']})",
        f"Target F-K Grade:      {target['fk_min']} - {target['fk_max']}",
        f"Target Flesch Ease:    {target['fre_min']} - {target['fre_max']}",
        f"Word Count Range:      {target['target_words']} words",
        f"Sentence Length Range: {target['avg_sentence_len']}",
        f"Total Iterations:      {len(history)}",
        "=" * 60,
        ""
    ]
    
    for step in history:
        m = step["metrics"]
        lines.extend([
            f"--- DRAFT {step['iteration']} STATISTICS ---",
            f"Title:                 {step['title']}",
            f"Word Count:            {m['word_count']}",
            f"Sentence Count:        {m['sentence_count']}",
            f"Avg Sentence Length:   {m['avg_sentence_length']} words",
            f"Flesch-Kincaid Grade:  {m['flesch_kincaid_grade']} (Pass: {m['fk_pass']})",
            f"Flesch Reading Ease:   {m['flesch_reading_ease']} (Pass: {m['fre_pass']})",
            f"Overall Status:        {'PASS' if m['overall_pass'] else 'FAIL'}",
        ])
        if m["suggestions"]:
            lines.append("Suggestions:")
            for sug in m["suggestions"]:
                lines.append(f"  * {sug}")
        
        lines.extend([
            "",
            "Draft Content Preview:",
            "-" * 40,
            step["text"][:300] + "..." if len(step["text"]) > 300 else step["text"],
            "-" * 40,
            "\n"
        ])
        
    final_step = history[-1]
    lines.extend([
        "=" * 60,
        "                  FINAL RESOLUTION",
        "=" * 60,
        f"Final Title:           {final_step['title']}",
        f"Final Word Count:      {final_step['metrics']['word_count']} words",
        f"Final F-K Grade:       {final_step['metrics']['flesch_kincaid_grade']}",
        f"Final Flesch Ease:     {final_step['metrics']['flesch_reading_ease']}",
        f"Status:                {'Calibrated successfully' if final_step['metrics']['overall_pass'] else 'Completed (Uncalibrated)'}",
        "=" * 60
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Calibrates and creates reading passages for Australian Curriculum Year levels.")
    parser.add_argument("--topic", help="The topic of the reading passage")
    parser.add_argument("--year_level", type=int, choices=range(1, 11), help="Australian Curriculum Year Level (1 to 10)")
    parser.add_argument("--length", type=int, help="Target word count")
    parser.add_argument("--output_dir", help="Directory where results will be written")
    parser.add_argument("--api_key", help="Gemini API Key (overrides environment variable)")
    parser.add_argument("--file", help="Analyse readability of an existing text file")
    parser.add_argument("--analyse_only", action="store_true", help="Perform analysis only and exit")
    parser.add_argument("--text", help="Provide completed text directly to skip generation and compile reports/docx")
    
    args = parser.parse_args()
    
    # 1. Single File Analysis Mode
    if args.file:
        if not os.path.exists(args.file):
            print(f"ERROR: File not found: {args.file}")
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
            
        if not args.year_level:
            print("ERROR: Please specify --year_level [1-10] to run analysis.")
            sys.exit(1)
            
        metrics = analyse_text_readability(content, args.year_level)
        print("\n" + "="*50)
        print(f"READABILITY ASSESSMENT: Year {args.year_level}")
        print("="*50)
        print(f"Word Count:          {metrics['word_count']}")
        print(f"Sentence Count:      {metrics['sentence_count']}")
        print(f"Avg Sentence Length: {metrics['avg_sentence_length']} words")
        print(f"F-K Grade Level:     {metrics['flesch_kincaid_grade']} (Target: {YEAR_LEVEL_TARGETS[args.year_level]['fk_min']}-{YEAR_LEVEL_TARGETS[args.year_level]['fk_max']})")
        print(f"Flesch Reading Ease: {metrics['flesch_reading_ease']} (Target: {YEAR_LEVEL_TARGETS[args.year_level]['fre_min']}-{YEAR_LEVEL_TARGETS[args.year_level]['fre_max']})")
        print(f"Overall Pass:        {metrics['overall_pass']}")
        if metrics["suggestions"]:
            print("\nSuggestions:")
            for sug in metrics["suggestions"]:
                print(f"  * {sug}")
        print("="*50)
        sys.exit(0)

    # 2. Text Compilation Mode (User provides text directly)
    if args.text:
        if not args.topic or not args.year_level or not args.output_dir:
            print("ERROR: --text requires --topic, --year_level, and --output_dir parameters.")
            sys.exit(1)
            
        os.makedirs(args.output_dir, exist_ok=True)
        metrics = analyse_text_readability(args.text, args.year_level)
        vocab = extract_vocabulary_definitions(args.text)
        
        # Write markdown text
        md_filename = f"{args.topic.replace(' ', '_')}_Y{args.year_level}.md"
        md_path = os.path.join(args.output_dir, md_filename)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {args.topic}\n\n{args.text}")
            
        # Write report
        report_filename = f"{args.topic.replace(' ', '_')}_Y{args.year_level}_Report.txt"
        report_path = os.path.join(args.output_dir, report_filename)
        history = [{"iteration": 1, "text": args.text, "title": args.topic, "metrics": metrics}]
        report_content = format_report_logs(args.topic, args.year_level, YEAR_LEVEL_TARGETS[args.year_level], history)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
            
        # Write Word Docx
        docx_filename = f"{args.topic.replace(' ', '_')}_Y{args.year_level}.docx"
        docx_path = os.path.join(args.output_dir, docx_filename)
        make_docx(args.topic, args.year_level, args.text, metrics["word_count"], vocab, docx_path)
        
        print(f"\nSuccessfully generated outputs in: {args.output_dir}")
        sys.exit(0)

    # 3. Interactive/Automatic Generation Mode
    if not args.topic or not args.year_level or not args.length or not args.output_dir:
        print("ERROR: Missing required parameters. Run with --help for options.")
        sys.exit(1)

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    os.makedirs(args.output_dir, exist_ok=True)
    
    if not api_key:
        # Interactive mode for workspace agent flow
        print("\n[LEVELED TEXT CREATOR - INTERACTIVE MODE]")
        print("No GEMINI_API_KEY environment variable detected.")
        print("Please draft the initial reading text based on the guidelines in SKILL.md and run analysis.")
        print(f"Target Year Level: Year {args.year_level} (Target F-K: {YEAR_LEVEL_TARGETS[args.year_level]['fk_min']}-{YEAR_LEVEL_TARGETS[args.year_level]['fk_max']})")
        print(f"Target Word Count: {args.length} words")
        print("\nOnce you have drafted the text, run compile with --text argument.")
        sys.exit(0)

    # Automatic iteration loop using Gemini API
    title, final_text, history = run_refinement_loop(api_key, args.topic, args.year_level, args.length)
    metrics = history[-1]["metrics"]
    vocab = extract_vocabulary_definitions(final_text)
    
    # Save outputs
    safe_topic = args.topic.replace(' ', '_')
    
    # Markdown
    md_path = os.path.join(args.output_dir, f"{safe_topic}_Y{args.year_level}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{final_text}\n")
        
    # Report Log
    report_path = os.path.join(args.output_dir, f"{safe_topic}_Y{args.year_level}_Report.txt")
    report_content = format_report_logs(args.topic, args.year_level, YEAR_LEVEL_TARGETS[args.year_level], history)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    # Docx
    docx_path = os.path.join(args.output_dir, f"{safe_topic}_Y{args.year_level}.docx")
    make_docx(title, args.year_level, final_text, metrics["word_count"], vocab, docx_path)
    
    print(f"\nSuccessfully generated outputs in: {args.output_dir}")
    print(f"  * Markdown: {md_path}")
    print(f"  * Report:   {report_path}")
    print(f"  * Word:     {docx_path}")


if __name__ == "__main__":
    main()
