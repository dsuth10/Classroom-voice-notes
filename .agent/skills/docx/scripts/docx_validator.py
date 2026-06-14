#!/usr/bin/env python3
"""
DocX Standards Validator - Antigravity Kit
==========================================

Scans .docx files and generated JS creation scripts for violations
of the professional standards defined in the DocX skill.
"""

import sys
import re
from pathlib import Path

# Fix Windows console encoding
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except:
    pass


def print_error(msg):
    print(f"\033[91m❌ {msg}\033[0m")

def print_success(msg):
    print(f"\033[92m✅ {msg}\033[0m")

def check_js_file(file_path):
    """Check docx-js creation scripts for common violations"""
    content = file_path.read_text(encoding='utf-8')
    violations = []

    # 1. Checklist for WidthType.PERCENTAGE
    if "WidthType.PERCENTAGE" in content:
        violations.append("Found WidthType.PERCENTAGE. Use WidthType.DXA for Google Docs compatibility.")

    # 2. Checklist for unicode bullets
    if re.search(r'TextRun\(["\']•', content) or "\\u2022" in content:
        violations.append("Found manual bullet characters. Use numbering config with LevelFormat.BULLET instead.")

    # 3. Checklist for standalone PageBreak
    if re.search(r'new PageBreak\(\)(?!\s*])', content):
        # This is a rough check, ideally we'd parse the AST
        if "children: [" not in content.split("new PageBreak()")[0]:
             violations.append("Potential standalone PageBreak detected. PageBreak must be inside a Paragraph.")

    # 4. Table dual width check (basic string check)
    if "Table({" in content and "columnWidths" not in content:
        violations.append("Table detected without columnWidths. Always set both table-level columnWidths and cell-level width.")

    return violations

def main():
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    success = True

    print(f"Checking DocX standards in: {project_root}")

    # Scan for JS creation scripts
    for js_file in project_root.rglob("*.js"):
        if "node_modules" in str(js_file):
            continue
        
        content = js_file.read_text(encoding='utf-8', errors='ignore')
        if "require('docx')" in content or 'from "docx"' in content:
            print(f"  Validating: {js_file.name}")
            violations = check_js_file(js_file)
            if violations:
                success = False
                for v in violations:
                    print_error(f"    {v}")
            else:
                print_success(f"    {js_file.name} adheres to standards.")

    if not success:
        sys.exit(1)
    
    print_success("DocX Standards Check PASSED")
    sys.exit(0)

if __name__ == "__main__":
    main()
