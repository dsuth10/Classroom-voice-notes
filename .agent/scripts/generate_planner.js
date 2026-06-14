const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType, LevelFormat, VerticalAlign } = require('docx');
const fs = require('fs');
const path = require('path');

// Document formatting constants
const MAIN_FONT = "Arial";
const PRIMARY_COLOR = "1E5128";
const SECONDARY_COLOR = "4E9F3D";
const LIGHT_BG = "F4F6F6";

// Table bordered style template
const tableBorder = { style: BorderStyle.SINGLE, size: 2, color: PRIMARY_COLOR };
const cellBorders = { top: tableBorder, bottom: tableBorder, left: tableBorder, right: tableBorder };

// Output directory
const outputDir = "c:\\Users\\dsuth\\Documents\\Joshua\\Units\\Science\\Unit 1 Biology Mould";

const doc = new Document({
  styles: {
    default: { document: { run: { font: MAIN_FONT, size: 24 } } }, // 12pt default
    paragraphStyles: [
      { 
        id: "Title", name: "Title", basedOn: "Normal",
        run: { size: 48, bold: true, color: PRIMARY_COLOR, font: MAIN_FONT }, // 24pt
        paragraph: { spacing: { before: 240, after: 120 }, alignment: AlignmentType.CENTER } 
      },
      { 
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, color: PRIMARY_COLOR, font: MAIN_FONT }, // 18pt
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 } 
      },
      { 
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, color: SECONDARY_COLOR, font: MAIN_FONT }, // 14pt
        paragraph: { spacing: { before: 180, after: 120 }, outlineLevel: 1 } 
      }
    ]
  },
  numbering: {
    config: [
      {
        reference: "procedure-list",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      }
    ]
  },
  sections: [{
    properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    children: [
      // Title
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun("Plant Germination Investigation Planner")] }),
      new Paragraph({ 
        alignment: AlignmentType.CENTER,
        spacing: { after: 240 },
        children: [new TextRun({ text: "Name: ______________________   Date: __________", size: 24 })] 
      }),

      // Part 1: Question
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("1. Our Question")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun("What are we trying to find out? Write your inquiry question below:")] }),
      new Paragraph({ spacing: { after: 360 }, children: [new TextRun({ text: "____________________________________________________________________________________", color: "CCCCCC" })] }),
      new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "____________________________________________________________________________________", color: "CCCCCC" })] }),

      // Part 2: Hypothesis
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("2. Our Hypothesis")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun("What do you think will happen? (I think that... because...)")] }),
      new Paragraph({ spacing: { after: 360 }, children: [new TextRun({ text: "____________________________________________________________________________________", color: "CCCCCC" })] }),
      new Paragraph({ spacing: { after: 360 }, children: [new TextRun({ text: "____________________________________________________________________________________", color: "CCCCCC" })] }),
      new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "____________________________________________________________________________________", color: "CCCCCC" })] }),

      // Part 3: Variables Table
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("3. Fair Testing (Our Variables)")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun("To make sure our test is fair, we must plan what we will change, measure, and keep the same.")] }),

      new Table({
        columnWidths: [3120, 3120, 3120], // 3 equal columns = 9360 total
        margins: { top: 150, bottom: 150, left: 150, right: 150 },
        rows: [
          // Header Row
          new TableRow({
            tableHeader: true,
            children: [
              new TableCell({
                borders: cellBorders, width: { size: 3120, type: WidthType.DXA },
                shading: { fill: PRIMARY_COLOR, type: ShadingType.CLEAR }, verticalAlign: VerticalAlign.CENTER,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "What we will CHANGE", bold: true, color: "FFFFFF" })] }),
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "(Circle ONE below)", size: 20, color: "FFFFFF" })] })
                ]
              }),
              new TableCell({
                borders: cellBorders, width: { size: 3120, type: WidthType.DXA },
                shading: { fill: PRIMARY_COLOR, type: ShadingType.CLEAR }, verticalAlign: VerticalAlign.CENTER,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "What we will MEASURE", bold: true, color: "FFFFFF" })] })
                ]
              }),
              new TableCell({
                borders: cellBorders, width: { size: 3120, type: WidthType.DXA },
                shading: { fill: PRIMARY_COLOR, type: ShadingType.CLEAR }, verticalAlign: VerticalAlign.CENTER,
                children: [
                  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "What we will KEEP THE SAME", bold: true, color: "FFFFFF" })] })
                ]
              })
            ]
          }),
          // Content Row (tall cell for writing)
          new TableRow({
            height: { value: 3000, rule: "atLeast" },
            children: [
              new TableCell({
                borders: cellBorders, width: { size: 3120, type: WidthType.DXA },
                children: [
                  new Paragraph({ spacing: { before: 100, after: 100 }, children: [new TextRun("O   Amount of Sunlight")] }),
                  new Paragraph({ spacing: { before: 100, after: 100 }, children: [new TextRun("O   Amount of Water")] }),
                  new Paragraph({ spacing: { before: 100, after: 100 }, children: [new TextRun("O   Growing Medium (Soil)")] }),
                  new Paragraph({ spacing: { before: 100, after: 100 }, children: [new TextRun("O   Temperature")] })
                ]
              }),
              new TableCell({
                borders: cellBorders, width: { size: 3120, type: WidthType.DXA },
                children: [
                  new Paragraph({ children: [new TextRun("")] })
                ]
              }),
              new TableCell({
                borders: cellBorders, width: { size: 3120, type: WidthType.DXA },
                children: [
                  new Paragraph({ children: [new TextRun("")] })
                ]
              })
            ]
          })
        ]
      }),

      // Page Break before Procedure
      new Paragraph({ pageBreakBefore: true, heading: HeadingLevel.HEADING_1, children: [new TextRun("4. Our Procedure")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun("Write the step-by-step instructions for how you will set up and run your experiment.")] }),
      
      ...Array.from({ length: 10 }).map(() => (
        new Paragraph({ 
          numbering: { reference: "procedure-list", level: 0 },
          spacing: { after: 360 },
          children: [new TextRun({ text: "__________________________________________________________________________", color: "CCCCCC" })] 
        })
      )),

      new Paragraph({ spacing: { before: 240 }, heading: HeadingLevel.HEADING_1, children: [new TextRun("5. Our Measurements & Findings")] }),
      new Paragraph({ spacing: { after: 120 }, children: [new TextRun("Record your observations here as you check on your plants over time:")] }),
      
      new Table({
        columnWidths: [1872, 5616, 1872], // Total 9360
        margins: { top: 100, bottom: 100, left: 100, right: 100 },
        rows: [
          new TableRow({
            tableHeader: true,
            children: [
              new TableCell({ borders: cellBorders, width: { size: 1872, type: WidthType.DXA }, shading: { fill: SECONDARY_COLOR, type: ShadingType.CLEAR }, children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Date", bold: true, color: "FFFFFF" })] })] }),
              new TableCell({ borders: cellBorders, width: { size: 5616, type: WidthType.DXA }, shading: { fill: SECONDARY_COLOR, type: ShadingType.CLEAR }, children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Observations (What do you see?)", bold: true, color: "FFFFFF" })] })] }),
              new TableCell({ borders: cellBorders, width: { size: 1872, type: WidthType.DXA }, shading: { fill: SECONDARY_COLOR, type: ShadingType.CLEAR }, children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Height (cm)", bold: true, color: "FFFFFF" })] })] }),
            ]
          }),
          ...Array.from({ length: 6 }).map(() => (
            new TableRow({
              height: { value: 700, rule: "atLeast" },
              children: [
                new TableCell({ borders: cellBorders, width: { size: 1872, type: WidthType.DXA }, children: [new Paragraph({ children: [new TextRun("")] })] }),
                new TableCell({ borders: cellBorders, width: { size: 5616, type: WidthType.DXA }, children: [new Paragraph({ children: [new TextRun("")] })] }),
                new TableCell({ borders: cellBorders, width: { size: 1872, type: WidthType.DXA }, children: [new Paragraph({ children: [new TextRun("")] })] })
              ]
            })
          ))
        ]
      }),
      
      new Paragraph({ spacing: { before: 240, after: 120 }, heading: HeadingLevel.HEADING_2, children: [new TextRun("Conclusion:")] }),
      new Paragraph({ spacing: { after: 360 }, children: [new TextRun({ text: "____________________________________________________________________________________", color: "CCCCCC" })] }),
      new Paragraph({ children: [new TextRun({ text: "____________________________________________________________________________________", color: "CCCCCC" })] }),

    ]
  }]
});

const outputPath = path.join(outputDir, "Plant_Germination_Investigation_Planner.docx");
Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`Successfully created: ${outputPath}`);
});
