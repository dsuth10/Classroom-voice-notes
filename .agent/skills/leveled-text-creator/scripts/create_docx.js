const fs = require('fs');
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, AlignmentType,
    PageOrientation, HeadingLevel, WidthType, ShadingType, VerticalAlign, BorderStyle } = require('docx');

// Check arguments
if (process.argv.length < 4) {
    console.error("Usage: node create_docx.js <input_json> <output_docx>");
    process.exit(1);
}

const inputJsonPath = process.argv[2];
const outputDocxPath = process.argv[3];

// Load and parse inputs
let data;
try {
    const rawData = fs.readFileSync(inputJsonPath, 'utf8');
    data = JSON.parse(rawData);
} catch (e) {
    console.error(`ERROR: Failed to read or parse input JSON file: ${e.message}`);
    process.exit(1);
}

const { title, year_level, text, word_count, vocabulary } = data;

// Build document children elements
const children = [];

// Header block styling
children.push(
    new Paragraph({
        heading: HeadingLevel.TITLE,
        spacing: { before: 0, after: 120 },
        children: [
            new TextRun({
                text: title || "Reading Passage",
                bold: true,
                size: 48, // 24pt
                color: "1B365D",
                font: "Arial"
            })
        ]
    })
);

// Subtitle block containing metadata
children.push(
    new Paragraph({
        spacing: { before: 0, after: 240 },
        border: {
            bottom: { style: BorderStyle.SINGLE, size: 8, color: "CCCCCC", space: 8 }
        },
        children: [
            new TextRun({
                text: `Curriculum level: Year ${year_level}  |  Length: ${word_count} words`,
                italics: true,
                size: 20, // 10pt
                color: "666666",
                font: "Arial"
            })
        ]
    })
);

// Spacer
children.push(new Paragraph({ spacing: { before: 120, after: 120 } }));

// Split text into paragraphs and build Word paragraphs
const textParagraphs = text.split(/\n+/);
textParagraphs.forEach(paraText => {
    const trimmed = paraText.trim();
    if (!trimmed) return;

    // Build the paragraph
    children.push(
        new Paragraph({
            spacing: { before: 0, after: 180, line: 286, lineRule: 'auto' }, // 1.3 line spacing for readability
            children: [
                new TextRun({
                    text: trimmed,
                    size: 22, // 11pt
                    color: "333333",
                    font: "Arial"
                })
            ]
        })
    );
});

// Append Vocabulary Callout Box if terms are present
if (vocabulary && Object.keys(vocabulary).length > 0) {
    children.push(new Paragraph({ spacing: { before: 240, after: 120 } }));
    
    children.push(
        new Paragraph({
            heading: HeadingLevel.HEADING_2,
            spacing: { before: 120, after: 120 },
            children: [
                new TextRun({
                    text: "Key Vocabulary",
                    bold: true,
                    size: 28, // 14pt
                    color: "1B365D",
                    font: "Arial"
                })
            ]
        })
    );

    const vocabRows = [];
    
    // Header for the Vocabulary box
    vocabRows.push(
        new TableRow({
            children: [
                new TableCell({
                    shading: { fill: "D5E8F0", type: ShadingType.CLEAR },
                    verticalAlign: VerticalAlign.CENTER,
                    borders: {
                        top: { style: BorderStyle.NONE },
                        bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
                        left: { style: BorderStyle.SINGLE, size: 24, color: "1B365D" },
                        right: { style: BorderStyle.NONE }
                    },
                    columnWidths: [8640], // US letter width minus 1" margins is 6.5 inches = 9360 DXA. Let's use ~8640 DXA.
                    children: [
                        new Paragraph({
                            spacing: { before: 120, after: 120 },
                            children: [
                                new TextRun({
                                    text: "Term & Context Explanation",
                                    bold: true,
                                    size: 18,
                                    color: "1B365D",
                                    font: "Arial"
                                })
                            ]
                        })
                    ]
                })
            ]
        })
    );

    // Populate terms
    Object.entries(vocabulary).forEach(([term, definition]) => {
        vocabRows.push(
            new TableRow({
                children: [
                    new TableCell({
                        shading: { fill: "F5F9FC", type: ShadingType.CLEAR },
                        verticalAlign: VerticalAlign.TOP,
                        borders: {
                            top: { style: BorderStyle.NONE },
                            bottom: { style: BorderStyle.SINGLE, size: 4, color: "EAEAEA" },
                            left: { style: BorderStyle.SINGLE, size: 24, color: "1B365D" },
                            right: { style: BorderStyle.NONE }
                        },
                        children: [
                            new Paragraph({
                                spacing: { before: 100, after: 100 },
                                children: [
                                    new TextRun({
                                        text: `${term}: `,
                                        bold: true,
                                        size: 18,
                                        color: "333333",
                                        font: "Arial"
                                    }),
                                    new TextRun({
                                        text: definition,
                                        size: 18,
                                        color: "444444",
                                        font: "Arial"
                                    })
                                ]
                            })
                        ]
                    })
                ]
            })
        );
    });

    const vocabTable = new Table({
        columnWidths: [8640],
        rows: vocabRows
    });

    children.push(vocabTable);
}

// Instantiate Document
const doc = new Document({
    styles: {
        default: {
            document: {
                run: { font: "Arial", size: 22, color: "333333" }
            }
        }
    },
    sections: [{
        properties: {
            page: {
                size: { width: 12240, height: 15840 }, // Explicit US Letter size
                margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } // 1 inch margins (1440 DXA)
            }
        },
        children: children
    }]
});

// Pack and write file
Packer.toBuffer(doc).then(buffer => {
    try {
        fs.writeFileSync(outputDocxPath, buffer);
        console.log(`Successfully generated DOCX at ${outputDocxPath}`);
    } catch (e) {
        console.error(`ERROR: Failed to write output DOCX file: ${e.message}`);
        process.exit(1);
    }
});
