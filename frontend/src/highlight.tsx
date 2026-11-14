import React, { useMemo } from "react";

type Language = "diff" | "json";

const JSON_TOKEN =
  /("(?:\\.|[^"\\])*")(\s*:)?|(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}\[\],:])/g;

function jsonNodes(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let end = 0;
  for (const match of text.matchAll(JSON_TOKEN)) {
    const start = match.index;
    if (start > end) nodes.push(text.slice(end, start));
    const [token, string, colon, number, literal] = match;
    if (string !== undefined) {
      nodes.push(
        <span
          key={start}
          className={
            colon === undefined
              ? "coordinator-json-string"
              : "coordinator-json-key"
          }
        >
          {string}
        </span>,
      );
      if (colon !== undefined) nodes.push(colon);
    } else if (number !== undefined) {
      nodes.push(
        <span key={start} className="coordinator-json-number">
          {number}
        </span>,
      );
    } else if (literal !== undefined) {
      nodes.push(
        <span key={start} className="coordinator-json-literal">
          {literal}
        </span>,
      );
    } else {
      nodes.push(token);
    }
    end = start + token.length;
  }
  if (end < text.length) nodes.push(text.slice(end));
  return nodes;
}

function diffClass(line: string): string | undefined {
  if (
    /^(diff --git |index |--- |\+\+\+ |new file mode |deleted file mode |rename (from|to) |\\ No newline)/.test(
      line,
    )
  )
    return "coordinator-diff-header";
  if (line.startsWith("@@")) return "coordinator-diff-hunk";
  if (line.startsWith("+")) return "coordinator-diff-add";
  if (line.startsWith("-")) return "coordinator-diff-remove";
  return undefined;
}

function diffNodes(text: string): React.ReactNode[] {
  return (text.match(/[^\n]*\n|[^\n]+$/g) || []).map((line, index) => {
    const className = diffClass(line);
    return className ? (
      <span key={index} className={className}>
        {line}
      </span>
    ) : (
      line
    );
  });
}

export function HighlightedText({
  text,
  language,
}: {
  text: string;
  language: Language;
}) {
  const nodes = useMemo(
    () => (language === "diff" ? diffNodes(text) : jsonNodes(text)),
    [language, text],
  );
  return <pre className="coordinator-highlight">{nodes}</pre>;
}
