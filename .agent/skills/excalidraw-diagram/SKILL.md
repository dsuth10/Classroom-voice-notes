---
name: excalidraw-diagram
description: Skill to give the AI the ability to generate beautiful and practical Excalidraw diagrams from natural language descriptions. Use when you need to create technical diagrams, flowcharts, or visual arguments. Supports rendering to PNG for visual validation.
---

# Excalidraw Diagram Skill

This skill allows you to generate diagrams that argue visually, rather than just displaying boxes and arrows.

## Design Methodology

### 1. Visual Arguments
Every shape should mirror the concept it represents:
- **Fan-outs**: Use for one-to-many relationships or data distribution.
- **Timelines**: Use for sequences, processes, or historical events.
- **Convergence**: Use for aggregation, synthesis, or "bottleneck" processes.
- **Evidence Artifacts**: Include realistic details like code snippets, JSON payloads, or data tables within the diagram.

### 2. Semantic Zoom Strategy
- **Level 1 (The Bird's Eye)**: High-level architecture, key actors, and primary flow.
- **Level 2 (The Component Zoom)**: Detailed breakdown of a specific module or sub-process.
- **Level 3 (The Implementation Detail)**: Actual payloads, interface definitions, or low-level logic.

### 3. Rendering Pipeline
The skill includes a script to render your `.excalidraw` JSON into a `.png` file. This is useful for:
- Providing the user with a ready-to-view image.
- Visual validation: You can "see" your own output through the renderer and fix layout issues (overlapping text, misaligned arrows) before delivery.

## Usage Workflow

1. **Map Concepts**: Identify the core argument of the request and choose appropriate visual patterns.
2. **Select Colours**: Use the semantic palette in `references/color-palette.md`.
3. **Generate JSON**: Use the templates in `references/element-templates.md` to build the diagram.
4. **Render**: (Optional) Run the render script to generate an image and validate the layout.
5. **Iterate**: If the design feels "loose" or lacks evidence, add more detail or tighten the layout.

## Configuration & References

- **Colours**: [color-palette.md](references/color-palette.md) - Semantic brand colours.
- **Templates**: [element-templates.md](references/element-templates.md) - JSON snippets for elements.
- **Schema**: [json-schema.md](references/json-schema.md) - Property reference.
- **Renderer**: Run `python .agent/skills/excalidraw-diagram/scripts/render_excalidraw.py <input.excalidraw>`.

## Setup Instructions

To enable the rendering pipeline:
1. Navigate to `.agent/skills/excalidraw-diagram/`
2. Run `uv sync` to install dependencies.
3. Run `uv run playwright install chromium`.
