import { expect, test } from "bun:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { HighlightedText } from "../src/highlight";

test("highlights diff structure without interpreting source text as HTML", () => {
  const markup = renderToStaticMarkup(
    <HighlightedText
      language="diff"
      text={
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+<new>\n context\n"
      }
    />,
  );
  expect(markup).toContain('class="coordinator-diff-header"');
  expect(markup).toContain('class="coordinator-diff-hunk"');
  expect(markup).toContain('class="coordinator-diff-remove"');
  expect(markup).toContain('class="coordinator-diff-add"');
  expect(markup).toContain("+&lt;new&gt;");
  expect(markup).toContain(" context");
});

test("highlights JSON keys, values, and escaped strings", () => {
  const markup = renderToStaticMarkup(
    <HighlightedText
      language="json"
      text={'{"name": "a\\\"<tag>", "count": 12.5, "ok": true, "empty": null}'}
    />,
  );
  expect(markup).toContain('class="coordinator-json-key"');
  expect(markup).toContain('class="coordinator-json-string"');
  expect(markup).toContain('class="coordinator-json-number"');
  expect(markup).toContain('class="coordinator-json-literal"');
  expect(markup).toContain("&lt;tag&gt;");
});
