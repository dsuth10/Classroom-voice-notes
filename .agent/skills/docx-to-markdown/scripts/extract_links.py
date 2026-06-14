import os
import sys
import xml.etree.ElementTree as ET

def extract_links(unpacked_dir):
    rels_path = os.path.join(unpacked_dir, 'word', '_rels', 'document.xml.rels')
    if not os.path.exists(rels_path):
        print(f"Error: {rels_path} not found")
        return []

    try:
        tree = ET.parse(rels_path)
        root = tree.getroot()
        
        # XML namespace for relationships
        ns = {'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
        
        links = []
        for rel in root.findall('rel:Relationship', ns):
            rel_type = rel.get('Type')
            if 'relationships/hyperlink' in rel_type:
                target = rel.get('Target')
                link_id = rel.get('Id')
                links.append({
                    'id': link_id,
                    'target': target
                })
        return links
    except Exception as e:
        print(f"Error parsing XML: {e}")
        return []

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_links.py <unpacked_dir>")
        sys.exit(1)
    
    unpacked_dir = sys.argv[1]
    links = extract_links(unpacked_dir)
    import json
    print(json.dumps(links, indent=2))
