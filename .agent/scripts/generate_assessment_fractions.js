const { Document, Packer, Paragraph, TextRun, AlignmentType } = require('docx');
const fs = require('fs');

const questions = [
  {
    q: "1. Which fraction is equivalent to 1/2?",
    options: ["A. 1/4", "B. 2/4", "C. 3/4", "D. 4/4"],
    ans: "ans: B"
  },
  {
    q: "2. If you have 2/4 of a pizza, how much pizza do you have?",
    options: ["A. 1/2", "B. 1/3", "C. 1/4", "D. 3/4"],
    ans: "ans: A"
  },
  {
    q: "3. Which of the following is equal to 1/5?",
    options: ["A. 2/10", "B. 3/10", "C. 4/10", "D. 5/10"],
    ans: "ans: A"
  },
  {
    q: "4. How many tenths are equal to 2/5?",
    options: ["A. 2/10", "B. 4/10", "C. 6/10", "D. 8/10"],
    ans: "ans: B"
  },
  {
    q: "5. Which fraction is another way to write 4/8? (Hint: think about halves and quarters)",
    options: ["A. 1/4", "B. 1/3", "C. 1/2", "D. 3/4"],
    ans: "ans: C"
  },
  {
    q: "6. What is 3/5 equivalent to in tenths?",
    options: ["A. 3/10", "B. 5/10", "C. 6/10", "D. 9/10"],
    ans: "ans: C"
  },
  {
    q: "7. If a chocolate bar is divided into 10 equal pieces and you eat 5 pieces, what fraction did you eat?",
    options: ["A. 1/5", "B. 2/5", "C. 1/2", "D. 3/5"],
    ans: "ans: C"
  },
  {
    q: "8. Which fraction is NOT equivalent to 1/2?",
    options: ["A. 2/4", "B. 3/6", "C. 5/10", "D. 2/5"],
    ans: "ans: D"
  },
  {
    q: "9. How many quarters make up one half?",
    options: ["A. 1", "B. 2", "C. 3", "D. 4"],
    ans: "ans: B"
  },
  {
    q: "10. Which equation is correct?",
    options: ["A. 1/5 = 5/10", "B. 4/5 = 8/10", "C. 1/2 = 1/5", "D. 2/4 = 3/4"],
    ans: "ans: B"
  }
];

const children = [];

for (let i = 0; i < questions.length; i++) {
  const item = questions[i];
  
  // Question
  children.push(new Paragraph({
    children: [new TextRun({ text: item.q, font: "Arial", size: 24 })],
    spacing: { before: 0, after: 0 }
  }));
  
  // Options
  for (const opt of item.options) {
    children.push(new Paragraph({
      children: [new TextRun({ text: opt, font: "Arial", size: 24 })],
      spacing: { before: 0, after: 0 }
    }));
  }
  
  // Answer
  children.push(new Paragraph({
    children: [new TextRun({ text: item.ans, font: "Arial", size: 24 })],
    spacing: { before: 0, after: 0 }
  }));
  
  // Empty space between questions (except after the last one)
  if (i < questions.length - 1) {
    children.push(new Paragraph({
      children: [new TextRun({ text: "", font: "Arial", size: 24 })],
      spacing: { before: 0, after: 0 }
    }));
  }
}

const doc = new Document({
  sections: [{
    properties: {
        page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
    },
    children: children
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("c:/Users/dsuth/Documents/Joshua/Units/Maths/Maths Unit 1/Equivalent_Fractions_Assessment.docx", buffer);
  console.log("Document generated successfully.");
});
