import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ParagraphView, plainText } from "@/components/report/paragraph";
import { ReportContext } from "@/components/report/report-context";
import type { Paragraph, Source } from "@/lib/types";

const source = { id: "src_1", number: 1, title: "Household survey, wave 2", domain: "stats.example", url: "https://stats.example/s",
  published_at: "2024-03-01" } as unknown as Source;

const p: Paragraph = {
  id: "p1",
  segments: [
    { text: "Adoption reached 58 percent by 2024.", evidence_ids: ["E3"], sources: [1], support: "supported", support_note: "" },
    { text: "This will likely double.", evidence_ids: [], sources: [], support: "uncited", support_note: "" },
    { text: "Costs fell sharply.", evidence_ids: ["E4"], sources: [1], support: "not_supported", support_note: "Quote mentions prices, not costs." },
  ],
} as Paragraph;

describe("cited paragraphs", () => {
  it("renders citation chips that open the exact supporting evidence", () => {
    const open = vi.fn();
    render(
      <ReportContext.Provider value={{ jobId: "job_1", sourcesByNumber: new Map([[1, source]]), open }}>
        <ParagraphView p={p} />
      </ReportContext.Provider>,
    );
    const chips = screen.getAllByRole("button", { name: /Source 1: Household survey/ });
    expect(chips).toHaveLength(2);
    fireEvent.click(chips[0]!);
    expect(open).toHaveBeenCalledWith({ sourceNumber: 1, evidenceIds: ["E3"], context: "Adoption reached 58 percent by 2024." });
  });

  it("visibly marks unsupported and uncited statements instead of hiding them", () => {
    render(
      <ReportContext.Provider value={{ jobId: "job_1", sourcesByNumber: new Map([[1, source]]), open: vi.fn() }}>
        <ParagraphView p={p} />
      </ReportContext.Provider>,
    );
    expect(screen.getByText("Costs fell sharply.").className).toMatch(/decoration-wavy/);
    expect(screen.getByText("This will likely double.").className).toMatch(/text-text-2/);
  });

  it("plain-text export keeps citation markers", () => {
    expect(plainText(p)).toBe("Adoption reached 58 percent by 2024.[1] This will likely double. Costs fell sharply.[1]");
  });
});
