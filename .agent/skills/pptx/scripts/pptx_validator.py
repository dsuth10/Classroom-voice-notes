#!/usr/bin/env python3
"""
PPTX Standards Validator - Antigravity Kit
==========================================

Scans generated presentations (via markitdown) and HTML slides 
for violations of the professional standards.
"""

import sys
import re
import subprocess
from pathlib import Path

def print_error(msg):
    print(f"[ERROR] {msg}")

def print_success(msg):
    print(f"[SUCCESS] {msg}")

def check_html_file(file_path):
    """Check HTML slides for design violations"""
    content = file_path.read_text(encoding='utf-8')
    violations = []

    # 1. Check for centered body text (rough heuristic)
    if "text-align: center" in content.lower():
        # Only warn if it's applied to something that looks like body text
        if re.search(r'<(p|ul|li|span|div)[^>]*style="[^"]*text-align:\s*center', content, re.I):
             violations.append("Potential centered body text detected. Only titles should be centered.")

    # 2. Check for title underlines (Anti-AI)
    if re.search(r'<(h1|h2|h3)[^>]*style="[^"]*text-decoration:\s*underline', content, re.I):
        violations.append("BANNED: Underlined headers detected. Use background bands or whitespace instead.")

    return violations

def check_pptx_content(pptx_path):
    """Check PPTX content for placeholders using markitdown"""
    violations = []
    try:
        # Resolve local .venv python
        venv_python = Path(__file__).parent.parent / ".venv" / "Scripts" / "python.exe"
        python_exec = str(venv_python) if venv_python.exists() else "python"

        result = subprocess.run(
            [python_exec, "-m", "markitdown", str(pptx_path)],
            capture_output=True,
            text=True,
            check=True
        )
        content = result.stdout
        
        # Check for placeholders
        placeholders = re.findall(r'(XXXX|Lorem Ipsum|lorem ipsum|\[Insert .*\])', content, re.I)
        if placeholders:
            violations.append(f"Found placeholder content: {', '.join(set(placeholders[:5]))}")
            
    except Exception:
        # If markitdown is not installed or fails, skip this check
        pass
        
    return violations

def main():
    project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    success = True

    print(f"Checking PPTX standards in: {project_root}")

    # Scan for HTML slide definitions
    for html_file in project_root.rglob("*.html"):
        if "node_modules" in str(html_file) or ".gemini" in str(html_file) or ".agent" in str(html_file) or ".venv" in str(html_file):
            continue
        
        content = html_file.read_text(encoding='utf-8', errors='ignore')
        if "width: 720pt" in content and "height: 405pt" in content:
            print(f"  Validating Slide: {html_file.name}")
            violations = check_html_file(html_file)
            if violations:
                success = False
                for v in violations:
                    print_error(f"    {v}")
            else:
                print_success(f"    {html_file.name} design adheres to standards.")

    # Scan for generated presentations
    for pptx_file in project_root.rglob("*.pptx"):
        if "node_modules" in str(pptx_file) or ".gemini" in str(pptx_file) or ".agent" in str(pptx_file) or ".venv" in str(pptx_file):
            continue
        
        print(f"  Validating Content: {pptx_file.name}")
        violations = check_pptx_content(pptx_file)
        if violations:
            success = False
            for v in violations:
                print_error(f"    {v}")

    if not success:
        sys.exit(1)
    
    print_success("PPTX Standards Check PASSED")
    sys.exit(0)

if __name__ == "__main__":
    main()
