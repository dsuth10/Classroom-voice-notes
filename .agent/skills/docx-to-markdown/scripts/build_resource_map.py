import os
import sys
import json
import yaml

def build_map(unit_dir):
    lessons_dir = os.path.join(unit_dir, 'Lessons')
    if not os.path.exists(lessons_dir):
        lessons_dir = os.path.join(unit_dir, 'Lesson_Plans')
    
    if not os.path.exists(lessons_dir):
        print(f"Error: Neither 'Lessons' nor 'Lesson_Plans' found in {unit_dir}")
        return
    
    unit_map = {
        "unit": os.path.basename(unit_dir),
        "lessons": []
    }
    
    for root, _, files in os.walk(lessons_dir):
        for filename in files:
            if filename.endswith('.md'):
                md_path = os.path.join(root, filename)
                with open(md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract frontmatter (naive split, but works for our script)
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        try:
                            data = yaml.safe_load(parts[1])
                            if not isinstance(data, dict):
                                continue
                            lesson_entry = {
                                "filename": os.path.relpath(md_path, lessons_dir).replace('\\', '/'),
                                "source_docx": data.get('source'),
                                "resources": []
                            }
                            
                            # Verify resources
                            for res in data.get('resources', []):
                                # The link is relative to the Lesson file
                                res_full_path = os.path.normpath(os.path.join(root, res))
                                exists = os.path.exists(res_full_path)
                                
                                lesson_entry["resources"].append({
                                    "target": res,
                                    "exists": exists,
                                    "type": "internal"
                                })
                            
                            for ext in data.get('external_links', []):
                                lesson_entry["resources"].append({
                                    "target": ext,
                                    "type": "external"
                                })
                                
                            unit_map["lessons"].append(lesson_entry)
                        except Exception as e:
                            print(f"Error parsing YAML in {filename}: {e}")
    
    output_path = os.path.join(unit_dir, 'resource_map.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unit_map, f, indent=2)
    
    return output_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python build_resource_map.py <unit_dir>")
        sys.exit(1)
    
    unit_dir = sys.argv[1]
    output = build_map(unit_dir)
    if output:
        print(f"Resource map created at {output}")
