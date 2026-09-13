import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { SourceText, sourceQuoteRanges } from './SourceText';
describe('SourceText',()=>{
 it('highlights exact evidence without changing the surrounding manuscript',()=>{
  const html=renderToStaticMarkup(<SourceText text={'앞 문장\n계약자만 사용할 수 있다.\n뒷 문장'} quote="계약자만 사용할 수 있다."/>);
  expect(html).toContain('<mark');expect(html).toContain('>계약자만 사용할 수 있다.</mark>');expect(html).toContain('앞 문장');expect(html).toContain('뒷 문장');
 });
 it('does not invent a match after a manuscript revision',()=>{
  const html=renderToStaticMarkup(<SourceText text="누구나 사용할 수 있다." quote="계약자만 사용할 수 있다."/>);
  expect(html).not.toContain('<mark');expect(html).toContain('현재 원고에서 이 인용문을 찾지 못했습니다');
 });
 it('highlights repeated quotes and warns that the location is ambiguous',()=>{
  const html=renderToStaticMarkup(<SourceText text="같은 말. 중간. 같은 말." quote="같은 말."/>);
  expect(html.match(/<mark/g)).toHaveLength(2);expect(html).toContain('같은 인용문이 2곳');
 });
 it('escapes manuscript HTML and ignores blank evidence',()=>{
  const html=renderToStaticMarkup(<SourceText text={'<script>bad()</script>'} quote="  "/>);
  expect(html).toContain('&lt;script&gt;');expect(html).not.toContain('<script>');expect(html).not.toContain('<mark');
 });
});
it('maps normalized chunk whitespace back to the original paragraph breaks',()=>{
 const html=renderToStaticMarkup(<SourceText text={'앞\n\n계약자는 검을 쓴다.\r\n\r\n  기억을 잃는다.\n끝'} quote={'계약자는 검을 쓴다.\n기억을 잃는다.'}/>);
 expect(html).toContain('<mark');expect(html).toContain('계약자는 검을 쓴다.\r\n\r\n  기억을 잃는다.</mark>');
});
it('never joins separate words to manufacture a match',()=>{
 const html=renderToStaticMarkup(<SourceText text="아버지 가방에 들어간다." quote="아버지가 방에 들어간다."/>);
 expect(html).not.toContain('<mark');
});
it('preserves original UTF-16 offsets with emoji and repeated normalized matches',()=>{
 const text='🗝️ 앞. 유나\n\n계약. 중간 🗡️ 유나\t계약. 끝.';
 const ranges=sourceQuoteRanges(text,'유나 계약.');
 expect(ranges).toHaveLength(2);
 expect(ranges.map(({start,end})=>text.slice(start,end))).toEqual(['유나\n\n계약.','유나\t계약.']);
});
it('does not accept punctuation changes as matching evidence',()=>{
 expect(sourceQuoteRanges('유나: 계약은 없다.','유나, 계약은 없다.')).toEqual([]);
});
