"use strict";

/* Line diff for the revise preview.

   The algorithm is a plain longest-common-subsequence walk, chosen because a
   mermaid source is small, line oriented, and read by a human who wants to see
   "one node was added here" rather than a minimal edit script. Two guards keep
   the quadratic table honest: identical leading and trailing lines are trimmed
   before the table is built (a revise usually touches one line in the middle),
   and if what remains would still exceed a cell budget the diff degrades to
   "all of the old, then all of the new" instead of freezing the tab.

   Rows are plain divs whose text is set with textContent, like every other
   string in this app. The diff never builds markup — the only place that does
   is the sanitised SVG in sanitize.js. */

const SFDiff = (window.SFDiff = {});

const MAX_CELLS = 250000;
const MARKS = { same: " ", add: "+", del: "−" };

function toLines(text) {
  return String(text === null || text === undefined ? "" : text).split("\n");
}

function row(type, text) {
  return { type: type, text: text };
}

function rowsOf(type, lines) {
  return lines.map((text) => row(type, text));
}

/* Backwards LCS table, then a forward walk that prefers a deletion when both
   directions are equally long — so a replaced line reads as "- old / + new". */
function lcsRows(a, b) {
  const n = a.length;
  const m = b.length;
  const table = [];
  for (let i = 0; i <= n; i += 1) table.push(new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i][j] =
        a[i] === b[j]
          ? table[i + 1][j + 1] + 1
          : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const rows = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push(row("same", a[i]));
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      rows.push(row("del", a[i]));
      i += 1;
    } else {
      rows.push(row("add", b[j]));
      j += 1;
    }
  }
  return rows.concat(rowsOf("del", a.slice(i)), rowsOf("add", b.slice(j)));
}

function diffLines(oldText, newText) {
  const a = toLines(oldText);
  const b = toLines(newText);
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
  let tail = 0;
  while (
    tail < a.length - head &&
    tail < b.length - head &&
    a[a.length - 1 - tail] === b[b.length - 1 - tail]
  ) {
    tail += 1;
  }
  const midA = a.slice(head, a.length - tail);
  const midB = b.slice(head, b.length - tail);
  const oversized = (midA.length + 1) * (midB.length + 1) > MAX_CELLS;
  const middle = oversized
    ? rowsOf("del", midA).concat(rowsOf("add", midB))
    : lcsRows(midA, midB);
  return rowsOf("same", a.slice(0, head)).concat(
    middle,
    rowsOf("same", tail ? a.slice(a.length - tail) : [])
  );
}

function summarise(rows) {
  return {
    added: rows.filter((item) => item.type === "add").length,
    removed: rows.filter((item) => item.type === "del").length,
    rows: rows.length,
  };
}

function rowNode(item) {
  const line = document.createElement("div");
  line.className = "diff-row diff-" + item.type;
  const sign = document.createElement("span");
  sign.className = "diff-sign";
  sign.textContent = MARKS[item.type];
  const body = document.createElement("span");
  body.className = "diff-text";
  body.textContent = item.text;
  line.appendChild(sign);
  line.appendChild(body);
  return line;
}

/* Draw the diff into `container` and hand back the counts for the summary. */
function render(container, oldText, newText) {
  const rows = diffLines(oldText, newText);
  const fragment = document.createDocumentFragment();
  rows.forEach((item) => fragment.appendChild(rowNode(item)));
  container.replaceChildren(fragment);
  return summarise(rows);
}

Object.assign(SFDiff, {
  diffLines: diffLines,
  summarise: summarise,
  render: render,
  MAX_CELLS: MAX_CELLS,
});
