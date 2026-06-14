const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const html2pptx = require('../skills/pptx/scripts/html2pptx.js');

const outputDir = "c:\\Users\\dsuth\\Documents\\Joshua\\Units\\Science\\Unit 1 Biology Mould";

async function createPresentation() {
    const pptx = new pptxgen();
    pptx.layout = 'LAYOUT_16x9';
    pptx.author = 'Science Teacher';
    pptx.title = 'Plant Germination Lesson';

    const rawHtml = fs.readFileSync(path.join(__dirname, 'slides.html'), 'utf-8');
    const header = rawHtml.substring(0, rawHtml.indexOf('<body>') + 6);
    const footer = "</body></html>";
    const slides = rawHtml.split('<!-- Slide');
    
    // Skip index 0 because it's the header before the first comment
    for (let i = 1; i < slides.length; i++) {
        console.log(`Generating Slide ${i}...`);
        // Re-construct a valid single-slide HTML document
        const slideHtml = header + "\n<!-- Slide" + slides[i] + "\n" + footer;
        const tmpFile = path.join(__dirname, `tmp_slide_${i}.html`);
        fs.writeFileSync(tmpFile, slideHtml);

        if (i === 5) { // The cup slide
            const { slide: slide5, placeholders } = await html2pptx(tmpFile, pptx);
            if (placeholders && placeholders.length > 0) {
                const ph = placeholders[0];
                slide5.addShape(pptx.shapes.TRAPEZOID, {
                    x: ph.x + (ph.w / 2) - 1.5, y: ph.y + 0.5, w: 3, h: 2,
                    fill: { color: "B2EBF2" }, line: { color: "00838F", width: 2 }, flipV: true
                });
                slide5.addText("Cup/Pot", {
                    x: ph.x, y: ph.y + 2.7, w: ph.w, h: 0.5,
                    align: 'center', color: "333333", bold: true, fontSize: 16
                });
            }
        } else {
            await html2pptx(tmpFile, pptx);
        }
        
        // Clean up
        fs.unlinkSync(tmpFile);
    }

    const outputPath = path.join(outputDir, 'Plant_Germination_Lesson.pptx');
    await pptx.writeFile({ fileName: outputPath });
    console.log(`Presentation created successfully at ${outputPath}`);
}

createPresentation().catch(err => {
    console.error("Error creating presentation:", err);
    process.exit(1);
});
