# Excalidraw JSON Schema

When generating diagrams, strictly adhere to the `excalidraw` file format version 2.

## Root Object
| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `type` | string | Yes | Must be `"excalidraw"` |
| `version` | number | Yes | Use `2` |
| `source` | string | No | URL or name of the generator |
| `elements` | array | Yes | Array of element objects |
| `appState` | object | No | View settings (background, etc.) |
| `files` | object | No | Referenced images or assets |

## Core Element Properties (Common to all)
| Property | Type | Description |
|----------|------|-------------|
| `type` | string | One of: `text`, `rectangle`, `ellipse`, `line`, `arrow`, `diamond` |
| `id` | string | Unique identifier |
| `x` | number | Top-left X coordinate |
| `y` | number | Top-left Y coordinate |
| `width` | number | Element width |
| `height` | number | Element height |
| `strokeColor` | string | Hex colour (pull from `color-palette.md`) |
| `backgroundColor` | string | Hex colour or `"transparent"` |
| `fillStyle` | string | `"solid"`, `"hachure"`, `"cross-hatch"` (usually `"solid"`) |
| `strokeWidth` | number | Usually `1` or `2` |
| `strokeStyle` | string | `"solid"`, `"dashed"`, `"dotted"` |
| `roughness` | number | `0` for clean lines, `1`+ for hand-drawn look (use `0`) |
| `opacity` | number | `0` to `100` |
| `groupIds` | array | Strings of group IDs the element belongs to |
| `roundness` | object | `{ "type": 3 }` for rounded corners on shapes |

## Text Properties
| Property | Type | Description |
|----------|------|-------------|
| `text` | string | Content of the text |
| `fontSize` | number | Size in pixels (usually `16` or `20`) |
| `fontFamily` | number | `1` (Virgil), `2` (Helvetica), `3` (Cascadia/Monospace) (use `3`) |
| `textAlign` | string | `"left"`, `"center"`, `"right"` |
| `verticalAlign` | string | `"top"`, `"middle"` |
| `containerId` | string | ID of the rectangle/ellipse this text is bound inside |

## Arrow/Line Properties
| Property | Type | Description |
|----------|------|-------------|
| `points` | array | Array of `[x, y]` relative to the element's base `x`, `y` |
| `startBinding` | object | `{ "elementId": "ID", "focus": number, "gap": number }` |
| `endBinding` | object | `{ "elementId": "ID", "focus": number, "gap": number }` |
| `startArrowhead`| string | `null`, `"arrow"`, `"bar"`, `"dot"` |
| `endArrowhead` | string | `null`, `"arrow"`, `"bar"`, `"dot"` |
