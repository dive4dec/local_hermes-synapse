#!/usr/bin/env node
// Render LaTeX math to inline SVG using MathJax liteAdaptor (no browser/jsdom needed)
// Input JSON on stdin: {"inline":["a+b"],"display":["x^2"]}
// Output JSON on stdout: {"inline":["<svg>...</svg>"],"display":["<svg>...</svg>"]}

const { mathjax } = require("mathjax-full/js/mathjax.js");
const { TeX } = require("mathjax-full/js/input/tex.js");
const { SVG } = require("mathjax-full/js/output/svg.js");
const { liteAdaptor } = require("mathjax-full/js/adaptors/liteAdaptor.js");
const { RegisterHTMLHandler } = require("mathjax-full/js/handlers/html.js");

const adaptor = liteAdaptor();
const handler = RegisterHTMLHandler(adaptor);
const tex = new TeX({});
const svg = new SVG({ fontCache: "local" });
const doc = mathjax.document("", { InputJax: tex, OutputJax: svg });

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
    const req = JSON.parse(input);
    const result = { inline: [], display: [] };

    for (const expr of (req.inline || [])) {
        const node = doc.convert(expr, { display: false, em: 12, ex: 5, containerWidth: 800 });
        result.inline.push(adaptor.innerHTML(node));
    }
    for (const expr of (req.display || [])) {
        const node = doc.convert(expr, { display: true, em: 12, ex: 5, containerWidth: 800 });
        result.display.push(adaptor.innerHTML(node));
    }

    process.stdout.write(JSON.stringify(result));
});
