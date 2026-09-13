import { describe, expect, it } from "vitest";
import { sortImportPaths } from "./importPaths";

describe("sortImportPaths", () => {
  it("sorts numbered episodes naturally instead of lexically", () => {
    expect(sortImportPaths(["/tmp/10화.txt", "/tmp/2화.txt", "/tmp/1화.txt"])).toEqual([
      "/tmp/1화.txt", "/tmp/2화.txt", "/tmp/10화.txt",
    ]);
  });

  it("handles Windows paths and keeps unnumbered files after numbered files", () => {
    expect(sortImportPaths(["C:\\draft\\부록.md", "C:\\draft\\12화.docx", "C:\\draft\\3화.txt"])).toEqual([
      "C:\\draft\\3화.txt", "C:\\draft\\12화.docx", "C:\\draft\\부록.md",
    ]);
  });
});
