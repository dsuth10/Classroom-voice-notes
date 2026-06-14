const { Document, Packer, Paragraph, TextRun } = require('docx');
const fs = require('fs');
const path = require('path');

const outputDir = "c:\\Users\\dsuth\\Documents\\Joshua\\Units\\Science\\Unit 1 Biology Mould";

const questions = [
  {
    q: "1. Why is it important for scientists to start an investigation with a clear question?",
    options: [
      "A. So they know exactly what they are trying to find out.",
      "B. Because it makes the experiment look more professional.",
      "C. So they can guess the answer before starting.",
      "D. So they don't have to write a hypothesis."
    ],
    ans: "A"
  },
  {
    q: "2. What is a hypothesis?",
    options: [
      "A. A list of materials needed for the experiment.",
      "B. The final result of an experiment.",
      "C. A prediction of what will happen, based on what you know.",
      "D. The step-by-step procedure to follow."
    ],
    ans: "C"
  },
  {
    q: "3. Which of the following is written as a good hypothesis?",
    options: [
      "A. I think plants are green.",
      "B. What will happen if I add more water to the seed?",
      "C. I think the seed with more sunlight will grow faster because plants need light for energy.",
      "D. The seed in the dark did not grow at all."
    ],
    ans: "C"
  },
  {
    q: "4. What is the main rule of a 'fair test'?",
    options: [
      "A. Change every variable so you can see many results.",
      "B. Change only one thing, measure one thing, and keep everything else the same.",
      "C. Make sure everyone gets a turn doing the experiment.",
      "D. Keep everything exactly the same and change nothing."
    ],
    ans: "B"
  },
  {
    q: "5. Sarah wants to see if seeds grow faster in soil or sand. She plants one seed in soil and puts it in the sun. She plants another seed in sand and puts it in a dark closet. Is this a fair test?",
    options: [
      "A. Yes, because she changed the growing medium.",
      "B. Yes, because she is testing two different things.",
      "C. No, because kept everything the same.",
      "D. No, because she changed two things (the growing medium and the amount of sunlight)."
    ],
    ans: "D"
  },
  {
    q: "6. Tom is testing how the amount of water affects plant growth. He gives Plant A 50mL of water and Plant B 100mL of water. Both plants are the same type, in the same soil, and get the same sunlight. Is this a fair test?",
    options: [
      "A. Yes, because he changed only one thing (the amount of water).",
      "B. No, because he needs to use different types of plants.",
      "C. Yes, because he changed the amount of sunlight.",
      "D. No, because Plant B is getting more water."
    ],
    ans: "A"
  },
  {
    q: "7. In a fair test about how temperature affects seed germination, what should be the ONLY thing you change?",
    options: [
      "A. The amount of water.",
      "B. The temperature.",
      "C. The type of seed.",
      "D. The amount of sunlight."
    ],
    ans: "B"
  },
  {
    q: "8. Emma tests if fertilizer helps seeds germinate. She uses Fertilizer A on a bean seed and Fertilizer B on a pea seed. Both get the same water and light. Is this a fair test?",
    options: [
      "A. Yes, because she used two types of fertilizer.",
      "B. Yes, because they had the same water and light.",
      "C. No, because she changed the type of seed along with the fertilizer.",
      "D. No, because she used the same amount of water."
    ],
    ans: "C"
  },
  {
    q: "9. Why do we write a step-by-step procedure for an experiment?",
    options: [
      "A. Only because the teacher said to.",
      "B. So that someone else can read it and do the exact same experiment.",
      "C. To make the experiment longer.",
      "D. So we can remember the results."
    ],
    ans: "B"
  },
  {
    q: "10. Which is the best instruction for a scientific procedure?",
    options: [
      "A. Put some water in.",
      "B. Add water to the cup.",
      "C. Pour 50mL of water into the plastic cup.",
      "D. Make it wet."
    ],
    ans: "C"
  }
];

const docChildren = [];
docChildren.push(new Paragraph({ children: [new TextRun({ text: "Plant Germination & Fair Testing Quiz", bold: true, size: 32 })] }));
docChildren.push(new Paragraph({ children: [new TextRun("")] }));

questions.forEach(q => {
  docChildren.push(new Paragraph({ children: [new TextRun(q.q)] }));
  q.options.forEach(opt => {
    docChildren.push(new Paragraph({ children: [new TextRun(opt)] }));
  });
  docChildren.push(new Paragraph({ children: [new TextRun(`ans: ${q.ans}`)] }));
  docChildren.push(new Paragraph({ children: [new TextRun("")] })); // Space between questions
});

const doc = new Document({
  sections: [{ properties: {}, children: docChildren }]
});

const outputPath = path.join(outputDir, "Plant_Germination_Assessment_Forms.docx");
Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`Successfully created: ${outputPath}`);
});
