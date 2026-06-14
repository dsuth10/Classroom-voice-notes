const { Document, Packer, Paragraph, TextRun, AlignmentType, Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType } = require('docx');
const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const html2pptx = require('c:\\Users\\dsuth\\Documents\\Joshua\\.agent\\skills\\pptx\\scripts\\html2pptx');

const THEME = { navy: '112d4e', orange: 'f96d00', white: 'f9f7f7', blue: '3f72af' };
const TEMPLATE_PATH = 'c:\\Users\\dsuth\\Documents\\Joshua\\.agent\\skills\\lesson-creator\\assets\\presentation_template.html';

/**
 * LESSON CREATOR RESOURCE GENERATOR
 * This script serves as a standardised template for generating Handouts, 
 * interactive HTML slide decks, optional static PPTX files, and MS Forms assessments.
 */

// --- STUDENT HANDOUT GENERATION ---
async function generateHandout(filename, data) {
  const doc = new Document({
    sections: [{
      children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: data.lessonTitle, bold: true, size: 32, color: THEME.navy })],
          spacing: { after: 200 }
        }),
        // dynamic handout structure ...
      ]
    }]
  });
  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(filename, buffer);
  console.log(`✅ Handout generated: ${path.basename(filename)}`);
}

// --- STANDALONE INTERACTIVE HTML PRESENTATION ---
/**
 * Compiles a structured array of slides into a single self-contained classroom presentation.
 * @param {string} outputFilename - Full path to write the output HTML file
 * @param {Object[]} slidesData - Array of slide objects
 */
async function generateHTMLPresentation(outputFilename, slidesData) {
  if (!fs.existsSync(TEMPLATE_PATH)) {
    throw new Error(`Presentation template wrapper not found at: ${TEMPLATE_PATH}`);
  }
  
  let templateContent = fs.readFileSync(TEMPLATE_PATH, 'utf8');
  
  // Standard template wrapper components integrity check
  const requiredMarkers = [
    'id="presentationContainer"',
    'id="masterToolbar"',
    'id="teacherNotesPanel"',
    'id="whiteboardOverlay"',
    'id="imageLightbox"',
    'id="teacherShowAnswerBtn"'
  ];
  requiredMarkers.forEach(marker => {
    if (!templateContent.includes(marker)) {
      throw new Error(`Wrapper Integrity Error: Standard template is missing required visual component marker "${marker}".`);
    }
  });

  let slidesHtml = '';
  
  slidesData.forEach((slide, idx) => {
    let slideClass = `slide theme-${slide.theme || 'light'}`;
    if (idx === 0) slideClass += ' active';
    
    let slideMarkup = `    <!-- SLIDE ${idx + 1}: ${slide.title} -->\n`;
    slideMarkup += `    <section class="${slideClass}" id="slide-${idx + 1}">\n`;
    
    // Slide Header
    if (slide.theme === 'dark') {
      slideMarkup += `      <div class="fade-in-up">\n        <h1>${slide.title}</h1>\n      </div>\n`;
      if (slide.subtitle) {
        slideMarkup += `      <div class="fade-in-up delay-1">\n        <p class="subtitle" style="font-size:26px; color:var(--text-light); margin-top:20px;">${slide.subtitle}</p>\n      </div>\n`;
      }
    } else {
      slideMarkup += `      <h2 class="slide-title fade-in-up">${slide.title}</h2>\n`;
    }
    
    // Content body
    slideMarkup += `      <div class="content fade-in-up delay-1">\n`;
    
    if (slide.lucasHtml) {
      slideMarkup += `        <!-- Standard Pathway Content -->\n`;
      slideMarkup += `        <div class="standard-only">\n          ${slide.standardHtml}\n        </div>\n`;
      slideMarkup += `        <!-- Lucas Pathway Content (Australian Curriculum v9 ICP compliant) -->\n`;
      slideMarkup += `        <div class="lucas-only">\n          ${slide.lucasHtml}\n        </div>\n`;
    } else {
      slideMarkup += `        <div>\n          ${slide.standardHtml}\n        </div>\n`;
    }
    
    // Slide specific Images
    if (slide.images && slide.images.length > 0) {
      slideMarkup += `        <div class="slide-images" style="display: flex; gap: 20px; margin-top: 25px; justify-content: center;">\n`;
      slide.images.forEach(img => {
        slideMarkup += `          <img src="${img}" style="max-height: 220px; border-radius: 6px; border: 1px solid #e2e8f0; box-shadow: var(--shadow-sm);" alt="${slide.title} Image">\n`;
      });
      slideMarkup += `        </div>\n`;
    }
    
    slideMarkup += `      </div>\n`;
    
    // Slide Teacher Notes
    if (slide.teacherNotes) {
      slideMarkup += `      <div class="teacher-notes" style="display: none;">\n        ${slide.teacherNotes}\n      </div>\n`;
    }
    
    slideMarkup += `    </section>\n\n`;
    slidesHtml += slideMarkup;
  });
  
  const placeholder = '<!-- SLIDES GO HERE DURING DYNAMIC COMPILATION -->';
  let compiledContent = templateContent.replace(placeholder, slidesHtml);
  
  fs.writeFileSync(outputFilename, compiledContent, 'utf8');
  console.log(`✅ Interactive HTML Presentation generated: ${path.basename(outputFilename)}`);
}

// --- OPTIONAL PPTX GENERATION (STATIC CONVERTER FALLBACK) ---
/**
 * Generates a PPTX presentation from an array of individual HTML slide files.
 * @param {string} filename - Output PPTX filename.
 * @param {string[]} slidePaths - Array of paths to INDIVIDUAL HTML slide files (1 file = 1 slide).
 */
async function generatePresentation(filename, slidePaths) {
  const pptx = new pptxgen();
  pptx.layout = 'LAYOUT_16x9';

  for (const s of slidePaths) {
    try {
      console.log(`Converting slide: ${path.basename(s)}`);
      await html2pptx(s, pptx);
    } catch (err) {
      console.error(`❌ Conversion error on ${s}: ${err.message}`);
      let failSlide = pptx.addSlide();
      failSlide.addText(`Slide generation failed: ${path.basename(s)}`, { x: 1, y: 1, color: 'FF0000', size: 18 });
    }
  }
  await pptx.writeFile({ fileName: filename });
  console.log(`✅ Static PPTX generated: ${path.basename(filename)}`);
}

// --- ASSESSMENT GENERATION ---
async function generateAssessment(filename, questions) {
  const docChildren = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "Assessment: " + data.title, bold: true, size: 32 })],
      spacing: { after: 400 }
    })
  ];
  // dynamic questions ...
  const doc = new Document({ sections: [{ children: docChildren }] });
  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(filename, buffer);
  console.log(`✅ Assessment generated: ${path.basename(filename)}`);
}

// --- MAIN RUN ---
async function run() {
  console.log("BOILERPLATE ENGINE ACTIVE. Copy/adapt this script when generating lessons.");
}

if (require.main === module) {
  run().catch(console.error);
}

module.exports = {
  generateHandout,
  generateHTMLPresentation,
  generatePresentation,
  generateAssessment
};
