#!/usr/bin/env python3
"""
NAPLAN Narrative Marking Report Generator

Generates a formatted markdown report from narrative assessment data.
"""

from typing import Dict, List
from datetime import datetime


def generate_report(
    narrative_text: str,
    scores: Dict[str, int],
    feedback: Dict[str, str],
    quotes: Dict[str, List[str]],
    strengths: List[str],
    weaknesses: List[str],
    recommendations: Dict[str, List[str]],
    total_score: int = None,
    max_score: int = 47
) -> str:
    """
    Generate a comprehensive NAPLAN narrative marking report.
    
    Args:
        narrative_text: The original narrative text
        scores: Dictionary of criterion name to score
        feedback: Dictionary of criterion name to detailed feedback
        quotes: Dictionary of criterion name to list of relevant quotes
        strengths: List of overall strengths
        weaknesses: List of overall weaknesses
        recommendations: Dictionary of criterion name to list of recommendations
        total_score: Total score (calculated if not provided)
        max_score: Maximum possible score (default 47)
    
    Returns:
        Formatted markdown report
    """
    
    if total_score is None:
        total_score = sum(scores.values())
    
    report_date = datetime.now().strftime("%d %B %Y")
    
    report = f"""# NAPLAN Narrative Marking Report
**Date:** {report_date}
**Total Score:** {total_score}/{max_score}

---

## Executive Summary

### Overall Strengths
"""
    
    for i, strength in enumerate(strengths, 1):
        report += f"{i}. {strength}\n"
    
    report += "\n### Areas for Development\n"
    
    for i, weakness in enumerate(weaknesses, 1):
        report += f"{i}. {weakness}\n"
    
    report += "\n---\n\n## Detailed Assessment by Criterion\n\n"
    
    # Criterion order and max scores
    criteria = [
        ("Audience", 6),
        ("Text Structure", 4),
        ("Ideas", 5),
        ("Character and Setting", 4),
        ("Vocabulary", 5),
        ("Cohesion", 4),
        ("Paragraphing", 2),
        ("Sentence Structure", 6),
        ("Punctuation", 5),
        ("Spelling", 6)
    ]
    
    for criterion, max_points in criteria:
        criterion_key = criterion.lower().replace(" ", "_")
        score = scores.get(criterion_key, 0)
        
        report += f"### {criterion} ({score}/{max_points} points)\n\n"
        
        # Feedback
        if criterion_key in feedback:
            report += f"**Assessment:**\n{feedback[criterion_key]}\n\n"
        
        # Quotes
        if criterion_key in quotes and quotes[criterion_key]:
            report += "**Evidence from text:**\n"
            for quote in quotes[criterion_key]:
                report += f'- "{quote}"\n'
            report += "\n"
        
        # Recommendations
        if criterion_key in recommendations and recommendations[criterion_key]:
            report += "**Recommendations:**\n"
            for rec in recommendations[criterion_key]:
                report += f"- {rec}\n"
            report += "\n"
        
        report += "---\n\n"
    
    report += "## Original Narrative Text\n\n"
    report += "```\n"
    report += narrative_text
    report += "\n```\n\n"
    
    report += "---\n\n"
    report += "*This report was generated using NAPLAN Narrative Marking guidelines.*\n"
    
    return report


def save_report(report: str, filename: str = None) -> str:
    """
    Save the report to a file.
    
    Args:
        report: The formatted report string
        filename: Output filename (auto-generated if not provided)
    
    Returns:
        Path to saved file
    """
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"naplan_report_{timestamp}.md"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    
    return filename


def format_score_table(scores: Dict[str, int]) -> str:
    """
    Generate a formatted table of scores.
    
    Args:
        scores: Dictionary of criterion name to score
    
    Returns:
        Markdown table string
    """
    table = "| Criterion | Score | Max |\n"
    table += "|-----------|-------|-----|\n"
    
    criteria = [
        ("Audience", 6),
        ("Text Structure", 4),
        ("Ideas", 5),
        ("Character and Setting", 4),
        ("Vocabulary", 5),
        ("Cohesion", 4),
        ("Paragraphing", 2),
        ("Sentence Structure", 6),
        ("Punctuation", 5),
        ("Spelling", 6)
    ]
    
    total = 0
    for criterion, max_points in criteria:
        criterion_key = criterion.lower().replace(" ", "_")
        score = scores.get(criterion_key, 0)
        total += score
        table += f"| {criterion} | {score} | {max_points} |\n"
    
    table += "|-----------|-------|-----|\n"
    table += f"| **TOTAL** | **{total}** | **47** |\n"
    
    return table


if __name__ == "__main__":
    # Example usage
    example_scores = {
        "audience": 4,
        "text_structure": 3,
        "ideas": 4,
        "character_and_setting": 3,
        "vocabulary": 4,
        "cohesion": 3,
        "paragraphing": 1,
        "sentence_structure": 4,
        "punctuation": 4,
        "spelling": 5
    }
    
    example_feedback = {
        "audience": "The narrative effectively engages the reader through deliberate language choices.",
        "text_structure": "Contains clear orientation, complication, and resolution with effective plot devices."
    }
    
    example_quotes = {
        "vocabulary": [
            "The wind clutched at her hair",
            "Her lungs screamed for air"
        ]
    }
    
    example_strengths = [
        "Strong vocabulary with precise word choices",
        "Clear narrative structure with effective complication"
    ]
    
    example_weaknesses = [
        "Limited paragraphing to pace the narrative",
        "Character development could be enhanced"
    ]
    
    example_recommendations = {
        "paragraphing": [
            "Use paragraphs to mark scene changes",
            "Consider single-sentence paragraphs for dramatic effect"
        ]
    }
    
    report = generate_report(
        narrative_text="Example narrative...",
        scores=example_scores,
        feedback=example_feedback,
        quotes=example_quotes,
        strengths=example_strengths,
        weaknesses=example_weaknesses,
        recommendations=example_recommendations
    )
    
    print(report)
