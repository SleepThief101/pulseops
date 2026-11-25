import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarkdownContent, normalizeMarkdownInput } from "../../components/MarkdownContent";

describe("MarkdownContent", () => {
  it("unescapes escaped markdown tokens outside fenced code blocks", () => {
    const raw =
      "\\#\\# Briefing\\n- \\*\\*Net MRR\\*\\*: \\$12,400\\n\\`subscription\\_charged\\`";
    const normalized = normalizeMarkdownInput(raw);
    expect(normalized).toContain("## Briefing");
    expect(normalized).toContain("- **Net MRR**");
    expect(normalized).toContain("`subscription_charged`");
  });

  it("renders headings, bold, lists, inline code, fenced code, and pipe tables", () => {
    const md = [
      "## Revenue Summary",
      "",
      "Live status for **Acme SaaS** (`org_1`):",
      "",
      "| Metric | Value |",
      "| --- | ---: |",
      "| Net MRR | $12,400.00 |",
      "| Churn Rate | 2.5% |",
      "",
      "- Checked `razorpay` connector",
      "- Verified *zero* pending alerts",
      "",
      "```json",
      '{"status": "ok"}',
      "```",
    ].join("\n");

    const html = renderToStaticMarkup(React.createElement(MarkdownContent, { content: md }));
    expect(html).toContain("<h2>Revenue Summary</h2>");
    expect(html).toContain("<strong>Acme SaaS</strong>");
    expect(html).toContain("<code>org_1</code>");
    expect(html).toContain("<table>");
    expect(html).toContain('<th style="text-align:right">Value</th>');
    expect(html).toContain("Net MRR");
    expect(html).toContain("$12,400.00");
    expect(html).toContain("<ul><li>");
    expect(html).toContain("<em>zero</em>");
    expect(html).toContain("<pre><code");
  });

  it("blocks javascript: URLs in markdown links", () => {
    const html = renderToStaticMarkup(
      React.createElement(MarkdownContent, {
        content: "[click](javascript:alert(1)) and [docs](https://example.com)",
      })
    );
    expect(html).not.toContain("javascript:");
    expect(html).toContain('href="https://example.com"');
  });
});
