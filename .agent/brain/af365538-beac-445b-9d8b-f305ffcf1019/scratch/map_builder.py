import os
import json
import yaml

def build_map(unit_root):
    # Search for all .md files in the unit_root subdirectories
    unit_map = {
        "unit": os.path.basename(unit_root),
        "lessons": []
    }
    
    for root, dirs, files in os.walk(unit_root):
        for filename in files:
            if filename.endswith('.md'):
                md_path = os.path.join(root, filename)
                with open(md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        try:
                            data = yaml.safe_load(parts[1])
                            lesson_entry = {
                                "filename": filename,
                                "path": os.path.relpath(md_path, unit_root),
                                "source_docx": data.get('source'),
                                "resources": []
                            }
                            
                            # Verify resources
                            for res in data.get('resources', []):
                                res_rel_path = res
                                res_full_path = os.path.normpath(os.path.join(root, res_rel_path))
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
                        except Exception:
                            pass # Skip if not a C2C MD with frontmatter
    
    output_path = os.path.join(unit_root, 'resource_map.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unit_map, f, indent=2)
    
    return output_path

if __name__ == "__main__":
    build_map(r"c:\Users\dsuth\Documents\Joshua\Units\HASS\Unit 2 Australians as global citizens")
