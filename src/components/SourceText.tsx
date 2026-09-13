import { Fragment } from 'react';

/** Collapse whitespace for comparison, while preserving offsets into the original. */
function normalizedSource(text: string) {
  const characters: string[] = [], starts: number[] = [], ends: number[] = [];
  for (let i = 0; i < text.length;) {
    const start = i;
    if (/\s/u.test(text[i])) {
      while (i < text.length && /\s/u.test(text[i])) i++;
      characters.push(' ');
    } else { characters.push(text[i]); i++; }
    starts.push(start); ends.push(i);
  }
  return { text: characters.join(''), starts, ends };
}

export function sourceQuoteRanges(text: string, quote?: string) {
  const needle = quote?.trim().replace(/\s+/gu, ' ');
  if (!needle) return [];
  const source = normalizedSource(text);
  const ranges: Array<{ start: number; end: number }> = [];
  let offset = 0;
  while (offset < source.text.length) {
    const index = source.text.indexOf(needle, offset);
    if (index < 0) break;
    ranges.push({ start: source.starts[index], end: source.ends[index + needle.length - 1] });
    offset = index + needle.length;
  }
  return ranges;
}

/** No fuzzy matching: changed words and punctuation never count as evidence. */
export function SourceText({ text, quote }: { text: string; quote?: string }) {
  const ranges = sourceQuoteRanges(text, quote);
  const matches = ranges.length;
  return <>
    {quote?.trim() && <p className="source-location-note" role="status">{matches === 0
      ? '현재 원고에서 이 인용문을 찾지 못했습니다. 수정 전 근거일 수 있으니 원문과 분석 시점을 확인해 주세요.'
      : matches > 1 ? `같은 인용문이 ${matches}곳 있습니다. 모두 강조했으니 앞뒤 문맥을 확인해 주세요.`
      : '선택한 근거와 일치하는 원문을 강조했습니다.'}</p>}
    <article>{ranges.map((range,index)=><Fragment key={range.start}>{text.slice(index ? ranges[index-1].end : 0, range.start)}<mark className="source-highlight" tabIndex={-1}>{text.slice(range.start,range.end)}</mark></Fragment>)}{text.slice(ranges.length ? ranges[ranges.length-1].end : 0)}</article>
  </>;
}
