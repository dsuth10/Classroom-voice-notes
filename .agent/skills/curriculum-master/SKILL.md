---
name: curriculum-master
description: Specialized skill for querying and analyzing Australian Curriculum v9 (AC v9) documents. Use this when you need to consult curriculum standards, find content descriptors for specific year levels (including bands like 5-6), or map lesson plans to the official standards.
---

# Curriculum Master

This skill provides robust tools and references for working with the Australian Curriculum v9 dataset in this project.

## Core Data Sources

- [**ac_v9_complete.json**](file:///c:/Users/dsuth/Documents/Joshua/ac_v9_complete.json): The primary source of truth for all curriculum standards.
- [**ac_v9_mapping_spec.md**](file:///c:/Users/dsuth/Documents/Joshua/docs/ac_v9_mapping_spec.md): Technical mapping rules.

## Workflow: Querying the Curriculum

To find specific content descriptors without facing terminal truncation or complex JSON parsing issues, use the provided Python script.

### Using the Query Script

```bash
python .agent/skills/curriculum-master/scripts/query_curriculum.py [options]
```

**Common Options:**
- `--learning_area <id>`: e.g., `the_arts`, `science`, `english`, `hass`, `mathematics`.
- `--year_level <level>`: e.g., `5`, `6`, `Foundation`. **Note:** This handles band-matching automatically (e.g., querying `5` will return `5-6` descriptors).
- `--strand <id>`: e.g., `music`, `biology`, `language`.
- `--format text`: Prints a human-readable list instead of raw JSON.

**Example: List Year 5 Music Descriptors**
```bash
python .agent/skills/curriculum-master/scripts/query_curriculum.py --learning_area the_arts --year_level 5 --strand music --format text
```

## References

- [**Schema Reference**](references/complete_v9_schema.md): Detailed breakdown of the JSON structure.

## Best Practices

1. **Always use the script**: Avoid reading the 10,000+ line JSON file directly if you only need a subset.
2. **Handle Bands**: Remember that AC v9 often groups years (e.g., 5-6). The query script handles this logic for you.
3. **Verify Codes**: Content descriptors are uniquely identified by their `code`.
