# AC v9 JSON Schema Reference

The `ac_v9_complete.json` file follows a hierarchical structure to represent the Australian Curriculum.

## Root Structure

- `$schema`: URL to draft-07 schema.
- `title`: Metadata title.
- `example`:
  - `curriculum`:
    - `version`: "9.0"
    - `learning_areas`: Array of [Learning Area](#learning-area-object)

## Learning Area Object

- `id`: Unique identifier (e.g., `english`, `mathematics`, `the_arts`, `science`, `hass`)
- `name`: Display name.
- `strands`: Array of [Strand](#strand-object)

## Strand Object

- `id`: Unique identifier (e.g., `language`, `music`, `science_understanding`)
- `name`: Display name.
- `content_descriptors`: Array of [Content Descriptor](#content-descriptor-object)

## Content Descriptor Object

- `code`: The AC code (e.g., `AC9E6LA01`)
- `year_level`: The targeted year (e.g., `6`, `1-2`, `Foundation`)
- `text`: The full instructional text.
- `strand_code`: Links back to parent strand ID.
- `sequence_number`: Order of appearance.

## Query Logic for Year levels

- **Bands**: Many descriptors use bands (e.g., `1-2`, `3-4`, `5-6`, `7-8`, `9-10`).
- **Matching**: When searching for "Year 5", you must include descriptors with `year_level == "5-6"`.
