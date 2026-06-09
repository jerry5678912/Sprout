"use strict";

function leadingWhitespace(text) {
  return String(text || "").match(/^\s*/)?.[0] || "";
}

function indentationWidth(text) {
  return leadingWhitespace(text).replace(/\t/g, "  ").length;
}

function isContinuationHeader(trimmed) {
  return /^(elif|else|catch|case)\b/.test(trimmed);
}

function previousContentLine(lines, index) {
  for (let cursor = index; cursor >= 0; cursor -= 1) {
    if (lines[cursor].trim() !== "") return cursor;
  }
  return -1;
}

function findIndentBlockEnd(lines, startLine, headerIndent) {
  let lastContent = startLine;
  for (let line = startLine + 1; line < lines.length; line += 1) {
    const text = lines[line];
    const trimmed = text.trim();
    if (trimmed === "") continue;
    const indent = indentationWidth(text);
    if (indent <= headerIndent && !isContinuationHeader(trimmed)) {
      break;
    }
    lastContent = line;
  }
  return lastContent;
}

function computeSproutFoldingRangesFromLines(lines) {
  const ranges = [];
  const explicitStack = [];
  for (let index = 0; index < lines.length; index += 1) {
    const text = lines[index];
    const trimmed = text.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    if (trimmed === "}" || trimmed === "end") {
      const opener = explicitStack.pop();
      if (opener) {
        const endLine = previousContentLine(lines, index);
        if (endLine > opener.start) {
          ranges.push({ start: opener.start, end: endLine, kind: "region" });
        }
      }
      continue;
    }

    if (/\{$/.test(trimmed)) {
      explicitStack.push({ start: index, kind: "brace" });
    } else if (/\bbloom\s*$/.test(trimmed)) {
      explicitStack.push({ start: index, kind: "bloom" });
    }

    if (/:\s*$/.test(trimmed)) {
      const endLine = findIndentBlockEnd(lines, index, indentationWidth(text));
      if (endLine > index) {
        ranges.push({ start: index, end: endLine, kind: "region" });
      }
    }
  }

  ranges.sort((a, b) => a.start - b.start || a.end - b.end);
  const deduped = [];
  const seen = new Set();
  for (const item of ranges) {
    const key = `${item.start}:${item.end}:${item.kind}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
  }
  return deduped;
}

function computeSproutFoldingRanges(text) {
  return computeSproutFoldingRangesFromLines(String(text || "").split(/\r?\n/));
}

module.exports = {
  computeSproutFoldingRanges,
  computeSproutFoldingRangesFromLines,
};
