# -*- coding: utf-8 -*-
"""
convert_lesson.py — C2C Lesson Docx → Markdown converter

Designed for Queensland C2C lesson plans, which use a two-column Word table:
  Left column  → Lesson concepts, HASS language, objectives, monitoring, etc.
  Right column → Main lesson body (learning sequence / review / assessment) +
                 Resources + Safety + Helpful information

Default workflow
----------------
1. Run pandoc with --wrap=none to get clean pipe-table markdown.
2. Walk each table row, collecting ALL cell text (both columns).
3. Recognise section headings by a comprehensive list of known C2C labels.
4. Reassemble as structured, readable Markdown.
5. Rewrite learningplace.eq.edu.au (and similar) resource URLs to local
   relative paths by matching against filenames in the Resources/ folder.
"""
import os
import sys
import subprocess
import zipfile
import xml.etree.ElementTree as ET
import yaml
import re
import urllib.parse

sys.path.append(os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# All known C2C section heading labels across lesson types
# ---------------------------------------------------------------------------

# These appear verbatim as the first piece of text in a pandoc table cell.
# Order matters: more specific phrases before shorter ones.
C2C_SECTIONS = [
    # Main body headings (right column)
    'Example learning sequence',
    'Example assessment sequence',
    'Review, reinforce and extend learning',
    'Assessment purpose',
    'Assessment concepts',
    'Resources (optional)',
    'Resources',
    'Helpful information',
    'Safety',
    # Metadata headings (left column)
    'Lesson concepts',
    'Assessment concepts',
    'Learning area specific language',
    'HASS language',
    'Lesson objectives',
    'Assessment objectives',
    'Evidence of learning',
    'Ideas for monitoring',
    'Learning alerts',
    'Suggested next steps for learning',
    'Ideas for differentiation',
    'Australian Curriculum references for this lesson',
    'Australian Curriculum references',
    'Relevant aspect of the achievement standard',
    # Differentiation sub-headings (appear as standalone lines)
    'Support',
    'Extension',
]

# Build a regex that matches any of the above exactly on a line
_SECTION_PATTERN = re.compile(
    r'^(' + '|'.join(re.escape(s) for s in C2C_SECTIONS) + r')\s*$',
    re.MULTILINE
)


# ---------------------------------------------------------------------------
# Resource resolution
# ---------------------------------------------------------------------------

def build_resource_index(resources_dir):
    """
    Scan Resources/ recursively and build:
      normalised_filename → actual_relative_path_from_resources_dir

    Normalisation: lowercase, strip spaces/hyphens/underscores.

    DEFAULT strategy — just scan the folder. Works for any unit where local
    files are named consistently with the source documents.
    """
    if not os.path.isdir(resources_dir):
        return {}
    index = {}
    for root, _, files in os.walk(resources_dir):
        for fname in files:
            rel = os.path.relpath(os.path.join(root, fname), resources_dir)
            key = fname.lower().replace(' ', '').replace('-', '').replace('_', '')
            index[key] = rel.replace('\\', '/')
    return index


def resolve_url_to_local(url, resource_index, resources_rel_path):
    """
    Map a publisher URL to a local resource file.

    Strategy
    1. Extract the URL basename (URL-decoded last path segment).
    2. Exact normalised match against the resource index.
    3. Suffix match fallback for files renamed between online and local copy
       (handles the e.g. mp4 prefix mismatch edge case).
    4. No match → return None (keep as genuine external URL).
    """
    parsed = urllib.parse.urlparse(url)
    basename = urllib.parse.unquote(parsed.path.split('/')[-1])
    if not basename:
        return None

    key = basename.lower().replace(' ', '').replace('-', '').replace('_', '')

    # 1. Exact match
    if key in resource_index:
        return f"{resources_rel_path}/{resource_index[key]}"

    # 2. Suffix match (min 10 normalised chars)
    for candidate_key, candidate_rel in resource_index.items():
        suffix_len = min(len(key), len(candidate_key))
        if suffix_len >= 10:
            tail = key[-(suffix_len // 2):]
            if tail and tail in candidate_key:
                return f"{resources_rel_path}/{candidate_rel}"

    return None


def rewrite_links_in_markdown(content, resource_index, resources_rel_path):
    """Replace [label](publisher_url) with [label](local_path) where possible."""
    def replace_md_link(match):
        label, url = match.group(1), match.group(2)
        local = resolve_url_to_local(url, resource_index, resources_rel_path)
        return f"[{label}]({local})" if local else match.group(0)

    return re.sub(r'\[([^\]]*)\]\((https?://[^\)]+)\)', replace_md_link, content)


# ---------------------------------------------------------------------------
# Link extraction from .rels (reads directly from zip, no unpacking)
# ---------------------------------------------------------------------------

def get_links_from_rels(docx_path):
    """Extract all hyperlinks from word/_rels/document.xml.rels inside the zip."""
    links = []
    try:
        with zipfile.ZipFile(docx_path) as z:
            rels = 'word/_rels/document.xml.rels'
            if rels in z.namelist():
                with z.open(rels) as f:
                    root = ET.parse(f).getroot()
                    ns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
                    for rel in root.findall('r:Relationship', ns):
                        if 'hyperlink' in rel.get('Type', ''):
                            links.append({'id': rel.get('Id'), 'target': rel.get('Target')})
    except Exception as e:
        print(f"  Warning: could not read rels: {e}")
    return links


# ---------------------------------------------------------------------------
# Table cell extractor
# ---------------------------------------------------------------------------

def extract_all_cell_text(pandoc_md):
    """
    Walk every row of every pandoc pipe-table and collect the text from
    ALL cells in document order (left column then right column per row).

    Returns a flat list of non-empty text strings.
    Preserves inline markdown (bold, italic, links).
    Strips: separator rows (+---+), image dimension attrs, HTML comments.
    """
    # Remove image dimension attributes first
    pandoc_md = re.sub(r'\{[^}]*width[^}]*\}', '', pandoc_md)
    pandoc_md = re.sub(r'\{[^}]*height[^}]*\}', '', pandoc_md)

    out = []
    for line in pandoc_md.split('\n'):
        stripped = line.strip()

        # Drop any line that consists entirely of table-structure characters.
        # This handles all pandoc grid/pipe-table separator row formats,
        # including very long or multi-format lines like:
        #   +--------+--------+
        #   |--------|--------|
        #   +===...===+===...===+
        # Strategy: remove all +, -, =, |, spaces — if nothing remains, it's a separator.
        if stripped and not re.sub(r'[-=+| ]', '', stripped):
            continue

        if line.startswith('|'):
            # Split cells on | but not on \|
            cells = re.split(r'(?<!\\)\|', line)
            for cell in cells:
                text = cell.strip().replace('<!-- -->', '').strip()
                if text:
                    out.append(text)
        else:
            # Non-table line — preserve blank lines as ''
            out.append(stripped)

    return out


# ---------------------------------------------------------------------------
# Icon alt-text rescue
# ---------------------------------------------------------------------------

def rescue_icon_alts(text):
    """
    C2C lesson plans embed concept key icons with verbose alt text like:
      '8047_C2C:DevArea:...:concept key:OA.png'
    followed by the actual label text.

    This function:
    - Extracts meaningful label text from those alts
    - Drops ACARA logo images
    - Drops icon images with no extractable label
    """
    def rescue_alt(match):
        alt = match.group(1).replace('\n', ' ').strip()
        path = match.group(2)

        if 'ACARA' in alt:
            return ''

        # C2C concept icon pattern: label appears after 'key:XX.png '
        if 'C2C:DevArea' in alt or 'concept' in alt.lower() or 'My Templates' in alt:
            label_match = re.search(r'key:[A-Z]+\.png\s+(.+)', alt)
            if label_match:
                label = label_match.group(1).strip()
                return f'**{label}**' if label else ''
            return ''

        return f'![{alt}]({path})'

    return re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', rescue_alt, text, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Main content cleaner
# ---------------------------------------------------------------------------

def clean_lesson_content(content):
    """
    Clean pandoc-converted C2C lesson Markdown.

    Handles all C2C lesson types:
      - Standard lessons       → 'Example learning sequence'
      - Review/extend lessons  → 'Review, reinforce and extend learning'
      - Assessment blocks      → 'Example assessment sequence' / 'Assessment purpose'

    The Word documents are one large two-column table. This function:
    1. Separates the YAML frontmatter.
    2. Rescues concept icon alt-texts.
    3. Extracts ALL cell text from every table row (both columns).
    4. Injects `##` headings and `---` dividers at recognised section names.
    5. Builds a clean document header from the lesson ID metadata.
    6. Collapses noise and applies Australian spelling.
    """
    # 1. Peel off frontmatter
    fm_match = re.match(r'^---\n.*?\n---\n', content, re.DOTALL)
    if fm_match:
        frontmatter = fm_match.group(0)
        body = content[len(frontmatter):]
    else:
        frontmatter, body = '', content

    # 2. Rescue icon alts
    body = rescue_icon_alts(body)

    # 3. Extract ALL cell text from tables
    cell_lines = extract_all_cell_text(body)

    # 4. Rebuild body — add section headings where recognised
    rebuilt = []
    for line in cell_lines:
        # Does this line exactly match a known section heading?
        if _SECTION_PATTERN.match(line.strip()):
            # Don't double-add a divider if preceding line is already one
            if rebuilt and rebuilt[-1] not in ('---', ''):
                rebuilt.append('')
                rebuilt.append('---')
                rebuilt.append('')
            elif not rebuilt:
                pass
            rebuilt.append(f'## {line.strip()}')
            rebuilt.append('')
        else:
            rebuilt.append(line)

    body = '\n'.join(rebuilt)

    # 5. Clean up structural noise
    body = body.replace('<!-- -->', '')
    # Long dash-only separator lines from nested tables
    body = re.sub(r'^[-]{10,}\s*$', '', body, flags=re.MULTILINE)
    # Multiple colons from header rows
    body = re.sub(r'^(#{1,6} #{1,6} #{1,6} )', '### ', body, flags=re.MULTILINE)
    # Collapse 3+ blank lines to 2
    body = re.sub(r'\n{3,}', '\n\n', body)

    # 6. Australian spelling
    body = body.replace('color', 'colour')
    body = body.replace('organize', 'organise')
    body = body.replace('program ', 'programme ')

    return frontmatter + body.strip() + '\n'


# ---------------------------------------------------------------------------
# Main conversion function
# ---------------------------------------------------------------------------

def convert_lesson(docx_path, output_md_path, resources_dir, resources_rel_path='../../Resources'):
    """
    Convert a single C2C lesson .docx to Markdown.

    Parameters
    ----------
    docx_path          : absolute path to the source .docx
    output_md_path     : absolute path for the output .md
    resources_dir      : absolute path to the local Resources/ folder
    resources_rel_path : relative path from the output .md to Resources/
                         (default '../../Resources' for a Lessons/ subfolder)
    """
    # 1. Build resource index (scan Resources/ folder)
    resource_index = build_resource_index(resources_dir)

    # 2. Get hyperlinks from the Word zip
    links = get_links_from_rels(docx_path)

    # 3. Classify links as resolved-local or external
    resolved_resources, external_links = [], []
    for link in links:
        target = link['target']
        if target.startswith('http'):
            local = resolve_url_to_local(target, resource_index, resources_rel_path)
            if local:
                resolved_resources.append(local)
            else:
                external_links.append(target)
        else:
            resolved_resources.append(target)

    # 4. pandoc conversion — use --wrap=none for clean pipe-table output
    os.makedirs(os.path.dirname(output_md_path), exist_ok=True)
    subprocess.run(
        ['pandoc', docx_path, '-o', output_md_path, '--wrap=none'],
        check=True
    )

    # 5. Read pandoc output
    with open(output_md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 6. Rewrite inline URLs to local paths
    content = rewrite_links_in_markdown(content, resource_index, resources_rel_path)

    # 7. Inject YAML frontmatter
    fm = {
        'source': os.path.basename(docx_path),
        'resources': resolved_resources,
        'external_links': external_links,
    }
    content = '---\n' + yaml.dump(fm, default_flow_style=False) + '---\n\n' + content

    # 8. Clean and structure
    content = clean_lesson_content(content)

    # 9. Write output
    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f'  OK: {os.path.basename(docx_path)} -> {os.path.basename(output_md_path)}')
    print(f'     Resources linked: {len(resolved_resources)}, External kept: {len(external_links)}')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print('Usage: python convert_lesson.py <docx_path> <output_md_path> <resources_dir> [resources_rel_path]')
        print()
        print('  docx_path          path to source .docx lesson')
        print('  output_md_path     path for output .md file')
        print('  resources_dir      path to Resources/ folder')
        print('  resources_rel_path optional relative path from md to Resources/ (default: ../../Resources)')
        sys.exit(1)

    convert_lesson(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3],
        sys.argv[4] if len(sys.argv) > 4 else '../../Resources'
    )
