import { describe, expect, it } from "vitest";

import { safeNext } from "@/components/auth-ui";
import { duration, formatBytes, hostname, safeHref } from "@/lib/utils";

describe("safeHref — only http(s) links are ever clickable", () => {
  it.each([
    ["javascript:alert(1)", null],
    ["data:text/html,<script>1</script>", null],
    ["upload://upl_123", null],
    ["not a url", null],
    ["", null],
    ["https://example.com/a?b=1", "https://example.com/a?b=1"],
    ["http://example.com", "http://example.com/"],
  ])("%s → %s", (input, out) => expect(safeHref(input)).toBe(out));
});

describe("safeNext — post-login redirects stay on this site", () => {
  it.each([
    ["/research/abc", "/research/abc"],
    ["//evil.example", "/dashboard"],
    ["https://evil.example", "/dashboard"],
    ["/\\evil.example", "/dashboard"],
    [null, "/dashboard"],
  ])("%s → %s", (input, out) => expect(safeNext(input)).toBe(out));
});

describe("formatting", () => {
  it("hostname strips www and tolerates junk", () => {
    expect(hostname("https://www.example.org/x")).toBe("example.org");
    expect(hostname("junk")).toBe("junk");
  });
  it("duration and bytes are human readable", () => {
    expect(duration(5)).toMatch(/5\s?s/);
    expect(duration(125)).toMatch(/2\s?m/);
    expect(formatBytes(2048)).toMatch(/2(\.0)?\s?KB/);
  });
});
