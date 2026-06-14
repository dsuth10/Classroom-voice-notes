import json
import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser(description='Query the Australian Curriculum v9 dataset.')
    parser.add_argument('--learning_area', help='ID of the learning area (e.g., the_arts, english)')
    parser.add_argument('--year_level', help='Year level filter (e.g., 5, 5-6, Foundation)')
    parser.add_argument('--strand', help='Strand ID (e.g., music, language)')
    parser.add_argument('--code', help='Specific content descriptor code to look up')
    parser.add_argument('--file', default='ac_v9_complete.json', help='Path to the curriculum JSON file')
    parser.add_argument('--format', choices=['json', 'text'], default='json', help='Output format')

    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)

    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        sys.exit(1)

    # Resolve learning areas
    curriculum = data.get('example', {}).get('curriculum', {})
    if not curriculum:
        # Check if it's the root as per some versions
        curriculum = data.get('curriculum', {})
    
    learning_areas = curriculum.get('learning_areas', [])
    
    results = []

    # Filter logic
    for la in learning_areas:
        if args.learning_area and la.get('id') != args.learning_area:
            continue
            
        for strand in la.get('strands', []):
            if args.strand and strand.get('id') != args.strand:
                continue
                
            # Check descriptors directly in strand
            for cd in strand.get('content_descriptors', []):
                process_cd(cd, strand, la, results, args)
            
            # Check descriptors in sub-strands
            for ss in strand.get('sub_strands', []):
                for cd in ss.get('content_descriptors', []):
                    process_cd(cd, strand, la, results, args, ss)

def process_cd(cd, strand, la, results, args, sub_strand=None):
    # Check code specifically
    if args.code and cd.get('code') != args.code:
        return
    
    # Check year level (handles bands like matching '5' to '5-6')
    if args.year_level:
        target = args.year_level
        actual = cd.get('year_level', '')
        if target != actual:
            # Logic for band matching: if target is in the band string
            if '-' in actual:
                parts = actual.split('-')
                if target not in parts and target != actual:
                    return
            else:
                return
    
    results.append({
        'code': cd.get('code'),
        'year_level': cd.get('year_level'),
        'text': cd.get('text'),
        'strand': strand.get('name'),
        'sub_strand': sub_strand.get('name') if sub_strand else None,
        'learning_area': la.get('id')
    })

    if not results:
        print("No matching descriptors found.")
        return

    if args.format == 'json':
        print(json.dumps(results, indent=2))
    else:
        for res in results:
            print(f"[{res['code']}] (Year {res['year_level']}) {res['text']}")

if __name__ == '__main__':
    main()
