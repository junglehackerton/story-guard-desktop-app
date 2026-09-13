import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { RelationEvidence } from "./Inspector";

it("offers an explicit source disclosure while evidence is loading", () => {
  const html = renderToStaticMarkup(<RelationEvidence relationId={42} />);
  expect(html).toContain("원문 근거 보기");
  expect(html).toContain("근거를 불러오는 중");
});
