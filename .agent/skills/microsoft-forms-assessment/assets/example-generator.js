const { Document, Packer, Paragraph, TextRun, AlignmentType } = require('docx');
const fs = require('fs');

/**
 * Generates a Microsoft Forms Assessment Word Document.
 * 
 * This template demonstrates the exact structure required for successful 
 * import into Microsoft Forms as described in the MS Forms Assessment skill.
 */

async function generateAssessment() {
    const doc = new Document({
        styles: {
            default: {
                document: {
                    run: {
                        font: "Arial",
                        size: 24, // 12pt
                    },
                },
            },
        },
        sections: [
            {
                properties: {},
                children: [
                    // Question 1 Block
                    new Paragraph({
                        children: [new TextRun({ text: "1. What two basic states of matter are mentioned in the text?", bold: true })],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("A. Solids and gases")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("B. Liquids and plasmas")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("C. Solids and liquids")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("D. None of the above")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("A N S : C")],
                        spacing: { after: 240 }, // Space after the answer notation (12pt)
                    }),

                    // Question 2 Block
                    new Paragraph({
                        children: [new TextRun({ text: "2. Which state of matter has a definite shape and volume?", bold: true })],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("A. Gas")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("B. Liquid")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("C. Solid")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("D. Plasma")],
                        spacing: { after: 0 },
                    }),
                    new Paragraph({
                        children: [new TextRun("A N S : C")],
                        spacing: { after: 240 },
                    }),
                ],
            },
        ],
    });

    const buffer = await Packer.toBuffer(doc);
    fs.writeFileSync("Assessment_Example.docx", buffer);
    console.log("Assessment_Example.docx created successfully.");
}

generateAssessment().catch(console.error);
