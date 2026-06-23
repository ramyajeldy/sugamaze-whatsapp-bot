const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType } = require('docx');
const fs = require('fs');

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

const TABLE_WIDTH = 9360;
const COL_NUM = 500;
const COL_Q = 4200;
const COL_A = 4660;

function headerCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: "2E5E4E", type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: "FFFFFF" })] })]
  });
}

function cell(text, width, opts = {}) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR } : undefined,
    children: [new Paragraph({ children: [new TextRun({ text, italics: opts.italic || false, color: opts.color })] })]
  });
}

// status: "ready" = grounded answer ready to use
//         "needs_input" = owner must fill in/edit
//         "escalate" = bot intentionally escalates instead of answering directly
const categories = [
  {
    name: "Hours & Location",
    items: [
      ["What are your store hours?", "Monday: 11:00 am - 8:00 pm. Tuesday: Closed. Wednesday to Friday: 11:00 am - 8:00 pm. Saturday & Sunday: 10:00 am - 9:00 pm.", "ready"],
      ["Where are you located?", "30 St Thomas St, Whitby, ON L1M 1H1 (Durham Region, Ontario).", "ready"],
      ["Are you open on Tuesdays?", "No, we're closed on Tuesdays. We're open all other days!", "ready"],
      ["What are your weekend hours?", "Saturday and Sunday: 10:00 am - 9:00 pm.", "ready"],
      ["Is there parking available at your store?", "[OWNER: please fill in parking details]", "needs_input"],
    ]
  },
  {
    name: "Ordering Process",
    items: [
      ["How do I place an order?", "You can order by calling +1 (905) 655-7878 or through our Contact Us page at sugamaze.ca/contact-us/.", "ready"],
      ["Can I order online?", "[OWNER: please confirm if there's an online ordering option beyond the contact form]", "needs_input"],
      ["How far in advance do I need to order a custom cake?", "[OWNER: please provide your lead time policy, e.g. '3-5 days notice']", "needs_input"],
      ["Do you take same-day orders?", "[OWNER: please confirm same-day order policy]", "needs_input"],
      ["Can I customize my cake design?", "Yes! Every cake is fully customizable - you can choose your size, flavour, and design. No two cakes are ever the same.", "ready"],
      ["Can I build my own custom cake?", "Yes, we have a custom cake builder where you can choose size, flavour, and design details.", "ready"],
      ["Do you require a deposit for custom orders?", "[OWNER: please confirm deposit policy]", "needs_input"],
      ["Can I see a design proof before the final cake is made?", "[OWNER: please confirm if design proofs/sketches are provided]", "needs_input"],
      ["What's the minimum order size?", "[OWNER: please provide minimum order details, if any]", "needs_input"],
      ["Can I order over the phone?", "Yes, you can call us directly at +1 (905) 655-7878 to place your order.", "ready"],
    ]
  },
  {
    name: "Pricing",
    items: [
      ["How much are your dessert cups?", "Dessert cups are $4.00 each.", "ready"],
      ["How much are macaroons?", "Macaroons are $12.00.", "ready"],
      ["How much does a birthday cake cost?", "[OWNER: most cakes are custom-quoted - please confirm a starting price range]", "needs_input"],
      ["How much does a wedding cake cost?", "[OWNER: please confirm a starting price range for wedding/tiered cakes]", "needs_input"],
      ["Do prices vary by cake size?", "[OWNER: please confirm - likely yes, larger sizes cost more]", "needs_input"],
      ["Is there an extra charge for custom designs?", "[OWNER: please confirm if elaborate designs cost more]", "needs_input"],
      ["Do you offer discounts for bulk orders?", "[OWNER: please confirm bulk order discount policy]", "needs_input"],
      ["What payment methods do you accept?", "[OWNER: please list accepted payment methods, e.g. cash, e-transfer, card]", "needs_input"],
      ["Do you require full payment upfront?", "[OWNER: please confirm payment timing policy]", "needs_input"],
      ["Are taxes included in the listed prices?", "[OWNER: please confirm if prices are tax-inclusive]", "needs_input"],
    ]
  },
  {
    name: "Cake Types & Occasions",
    items: [
      ["Do you make wedding cakes?", "Yes! Wedding cakes are one of our specialties - custom tiered cakes, all 100% eggless, with options for different flavours, sizes, and designs.", "ready"],
      ["Do you make birthday cakes?", "Yes, custom-designed birthday cakes for all ages and themes.", "ready"],
      ["Do you make anniversary cakes?", "Yes, we make custom anniversary cakes.", "ready"],
      ["Do you make gender reveal cakes?", "Yes, we make gender reveal cakes.", "ready"],
      ["Do you make graduation cakes?", "Yes, we make graduation cakes.", "ready"],
      ["Do you make Valentine's cakes?", "Yes, we make Valentine cakes.", "ready"],
      ["Do you make Sweet 16 cakes?", "Yes, we make Sweet 16 cakes.", "ready"],
      ["Do you make theme-based cakes?", "Yes, we make theme-based cakes for any occasion.", "ready"],
      ["Do you make photo cakes?", "Yes, we make photo cakes with edible printed images.", "ready"],
      ["What are ready-to-eat cakes?", "Ready-to-go cakes are freshly baked and available without a custom order wait - great for last-minute celebrations.", "ready"],
      ["Do you make cupcakes?", "Yes, we make cupcakes.", "ready"],
      ["Do you make cake pops?", "Yes, we make cake pops.", "ready"],
      ["Do you make patties or puffs?", "Yes, we make patties/puffs.", "ready"],
      ["Do you make cakes for corporate events?", "[OWNER: please confirm if you cater corporate/office events]", "needs_input"],
      ["Do you make 3D/sculpted cakes?", "[OWNER: please confirm if 3D/sculpted cake designs are offered]", "needs_input"],
    ]
  },
  {
    name: "Eggless & Dietary (Allergy questions are escalated, not auto-answered)",
    items: [
      ["Are your cakes eggless?", "Yes! All Sugamaze cakes are 100% eggless.", "ready"],
      ["Are your cakes vegan?", "(Escalated to shop owner for accurate, safety-checked answer.)", "escalate"],
      ["Are your cakes gluten-free?", "(Escalated to shop owner for accurate, safety-checked answer.)", "escalate"],
      ["Do your cakes contain nuts?", "(Escalated to shop owner for accurate, safety-checked answer.)", "escalate"],
      ["Can you accommodate dairy-free requests?", "(Escalated to shop owner for accurate, safety-checked answer.)", "escalate"],
    ]
  },
  {
    name: "Delivery & Pickup",
    items: [
      ["Do you offer delivery?", "[OWNER: please confirm if delivery is offered]", "needs_input"],
      ["What areas do you deliver to?", "[OWNER: please list delivery areas, e.g. Whitby, Durham Region, GTA]", "needs_input"],
      ["Is there a delivery fee?", "[OWNER: please confirm delivery fee policy]", "needs_input"],
      ["Can I pick up my order in-store?", "Yes, Sugamaze is a storefront bakery at 30 St Thomas St, Whitby, ON - you're welcome to pick up in-store.", "ready"],
      ["What's your delivery timeframe?", "[OWNER: please confirm typical delivery windows]", "needs_input"],
      ["Do you deliver to Toronto?", "[OWNER: please confirm if Toronto is within your delivery area]", "needs_input"],
      ["Do you deliver outside Durham Region?", "[OWNER: please confirm delivery range]", "needs_input"],
      ["Can I schedule a specific delivery time?", "[OWNER: please confirm if scheduled delivery windows are available]", "needs_input"],
      ["Do you deliver on weekends?", "[OWNER: please confirm weekend delivery availability]", "needs_input"],
      ["Is curbside pickup available?", "[OWNER: please confirm if curbside pickup is offered]", "needs_input"],
    ]
  },
  {
    name: "Cancellations & Refunds",
    items: [
      ["What is your cancellation policy?", "Cancellations must be made at least 5 days in advance for a full refund. Cancellations after that cutoff are non-refundable.", "ready"],
      ["What is your refund policy?", "You may qualify for a refund if you received the wrong order or your order was not delivered. Email info@sugamaze.ca with your order number, a description of the issue, and photos if applicable.", "ready"],
      ["Can I get a refund if I don't like the design?", "Minor design variations are not grounds for a refund, since every cake is hand-crafted and slight differences from photos are normal.", "ready"],
      ["Can I get a refund for taste preference?", "No, personal taste preference is not grounds for a refund since flavours are agreed upon in advance.", "ready"],
      ["What if I receive the wrong order?", "You're eligible for a refund. Email info@sugamaze.ca with your order number, a description of the issue, and photos if possible.", "ready"],
      ["What if my order wasn't delivered?", "You're eligible for a refund. Email info@sugamaze.ca with your order number and details.", "ready"],
      ["How do I request a refund?", "Email info@sugamaze.ca with your order number, a description of the issue, and photos if applicable.", "ready"],
      ["Can I reschedule my order date instead of cancelling?", "[OWNER: please confirm if rescheduling is allowed instead of cancelling]", "needs_input"],
    ]
  },
  {
    name: "Cake Care & Storage",
    items: [
      ["How do I store my cake?", "[OWNER: please confirm general storage instructions, e.g. refrigeration]", "needs_input"],
      ["Should I remove the dowel rods before serving?", "Yes, always remove all internal dowel/support rods from tiered cakes before cutting and serving.", "ready"],
      ["Are the cake decorations edible?", "Always remove decorative elements before serving - some may contain non-edible materials that are a choking risk, especially for children.", "ready"],
      ["Is it safe to serve cake to children?", "Yes, but always supervise young children when serving decorated cakes, and remove any non-edible decorations first.", "ready"],
      ["How long can strawberry cakes be kept?", "Strawberry cakes (with fresh strawberries inside or as decoration) should be eaten the same day for best quality and safety.", "ready"],
      ["Why does dark frosting taste different?", "Dark colors (black, navy, deep red) may taste slightly bitter and can temporarily stain hands or lips. Lighter alternatives are available, or dark frosting can be removed before eating.", "ready"],
      ["How long does the cake stay fresh?", "[OWNER: please confirm general freshness window, e.g. '2-3 days at room temp, 5 days refrigerated']", "needs_input"],
      ["Can I freeze the cake?", "[OWNER: please confirm if freezing is recommended/safe for your cakes]", "needs_input"],
    ]
  },
  {
    name: "Sizes & Servings",
    items: [
      ["What cake sizes are available?", "We offer 6\", 8\", 10\", and 12\" sizes.", "ready"],
      ["How many people does a 6-inch cake serve?", "[OWNER: please provide serving size estimate]", "needs_input"],
      ["How many people does an 8-inch cake serve?", "[OWNER: please provide serving size estimate]", "needs_input"],
      ["How many people does a 10-inch cake serve?", "[OWNER: please provide serving size estimate]", "needs_input"],
      ["Can I order a half cake/sheet cake?", "[OWNER: please confirm if sheet cakes or half-cakes are offered]", "needs_input"],
      ["Do you make tiered cakes for small parties?", "[OWNER: please confirm minimum tier sizing options]", "needs_input"],
      ["What's the largest cake size you offer?", "[OWNER: please confirm largest available size, especially for tiered/wedding cakes]", "needs_input"],
      ["Can I mix flavors in a tiered cake?", "[OWNER: please confirm if different tiers can have different flavours]", "needs_input"],
    ]
  },
  {
    name: "Flavors & Design",
    items: [
      ["What flavors do you offer?", "[OWNER: please list available flavours]", "needs_input"],
      ["Do you have chocolate cake?", "[OWNER: please confirm]", "needs_input"],
      ["Do you have red velvet?", "[OWNER: please confirm]", "needs_input"],
      ["Can I send a reference photo for my cake design?", "[OWNER: please confirm if reference photos are accepted]", "needs_input"],
      ["Do you do fondant cakes?", "[OWNER: please confirm if fondant finishing is offered]", "needs_input"],
      ["Do you do buttercream cakes?", "[OWNER: please confirm if buttercream finishing is offered]", "needs_input"],
      ["Can I request a specific color scheme?", "Yes, all cakes are custom-designed, so you can request specific colors as part of your design.", "ready"],
      ["Do you write custom messages on cakes?", "[OWNER: please confirm if custom text/messages can be added]", "needs_input"],
    ]
  },
  {
    name: "Misc / Business",
    items: [
      ["How can I contact you?", "Call us at +1 (905) 655-7878, email info@sugamaze.ca, or visit sugamaze.ca/contact-us/.", "ready"],
      ["What's your phone number?", "+1 (905) 655-7878", "ready"],
      ["What's your email?", "info@sugamaze.ca", "ready"],
      ["Do you have a physical storefront I can visit?", "Yes! Sugamaze is a storefront bakery located at 30 St Thomas St, Whitby, ON L1M 1H1. You can also find our address on sugamaze.ca.", "ready"],
      ["Do you sell gift cards?", "[OWNER: please confirm if gift cards are available]", "needs_input"],
      ["Do you do cake tastings?", "[OWNER: please confirm if tastings are offered]", "needs_input"],
      ["Are you on Instagram/Facebook?", "[OWNER: please provide social media handles/links]", "needs_input"],
      ["Do you cater large events?", "[OWNER: please confirm event catering capacity/policy]", "needs_input"],
      ["Do you offer cake decorating classes?", "[OWNER: please confirm if classes/workshops are offered]", "needs_input"],
      ["Who founded Sugamaze?", "Sugamaze was founded by Srivani, the creative baker behind Sugamaze, known for custom, celebration, and eggless cakes.", "ready"],
      ["Do you have a loyalty/rewards program?", "[OWNER: please confirm if a loyalty program exists]", "needs_input"],
      ["Can I visit the bakery to pick out designs in person?", "Yes, you're welcome to visit our storefront at 30 St Thomas St, Whitby, ON to discuss designs in person.", "ready"],
    ]
  },
];

const statusColor = { ready: "1B5E20", needs_input: "B45309", escalate: "8E24AA" };
const statusLabel = { ready: "READY", needs_input: "NEEDS INPUT", escalate: "ESCALATE" };

const children = [
  new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun("Sugamaze WhatsApp Bot — FAQ Review")]
  }),
  new Paragraph({
    children: [new TextRun({
      text: "Review each answer below. Edit any text directly in this document — especially items marked NEEDS INPUT (orange) which need real answers from you. Items marked ESCALATE (purple) are intentionally not auto-answered (e.g. allergy questions) and will instead notify the shop owner. Once you're happy, send this file back and it will be added to the bot's knowledge base.",
      italics: true
    })]
  }),
  new Paragraph({ children: [new TextRun("")] }),
];

let qNum = 1;
for (const cat of categories) {
  children.push(new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun(cat.name)]
  }));

  const rows = [
    new TableRow({
      children: [
        headerCell("#", COL_NUM),
        headerCell("Question", COL_Q),
        headerCell("Answer", COL_A),
      ]
    })
  ];

  for (const [q, a, status] of cat.items) {
    rows.push(new TableRow({
      children: [
        cell(String(qNum), COL_NUM),
        cell(q, COL_Q),
        cell(`[${statusLabel[status]}] ${a}`, COL_A, { color: statusColor[status] }),
      ]
    }));
    qNum++;
  }

  children.push(new Table({
    width: { size: TABLE_WIDTH, type: WidthType.DXA },
    columnWidths: [COL_NUM, COL_Q, COL_A],
    rows
  }));
  children.push(new Paragraph({ children: [new TextRun("")] }));
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: "2E5E4E" },
        paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: "2E5E4E" },
        paragraph: { spacing: { before: 300, after: 120 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    children
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("Sugamaze_FAQ_Review.docx", buffer);
  console.log("Document created: Sugamaze_FAQ_Review.docx");
});
