import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import type { StoryDocument } from '../lib/types';
const PAGE_SIZE = 12;
export function DocumentPicker({ documents, selectedId, onSelect, revealKey }: {
  documents: StoryDocument[]; selectedId?: number; revealKey?: object; onSelect: (id: number) => void;
}) {
  const [query, setQuery] = useState('');
  const localSelection = useRef<number>();
  const lastRevealKey = useRef(revealKey);
  const [page, setPage] = useState(0);
  const ordered = useMemo(() => [...documents].sort((a,b) => a.chapter_index-b.chapter_index), [documents]);
  // Evidence navigation should reveal the selected chapter, even after a search.
  useEffect(() => {
    const externalNavigation = lastRevealKey.current !== revealKey;
    lastRevealKey.current = revealKey;
    if (!externalNavigation && localSelection.current === selectedId) { localSelection.current = undefined; return; }
    localSelection.current = undefined;
    setQuery('');
    setPage(Math.max(0, Math.floor(ordered.findIndex(doc => doc.id === selectedId) / PAGE_SIZE)));
  }, [selectedId, revealKey]);
  const filtered = ordered.filter(doc => `${doc.chapter_index+1}화 ${doc.title}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const pageCount = Math.max(1, Math.ceil(filtered.length/PAGE_SIZE));
  const currentPage = Math.min(page, pageCount-1);
  const visible = filtered.slice(currentPage*PAGE_SIZE, (currentPage+1)*PAGE_SIZE);
  return <div className="document-browser">
    <label className="document-search">회차·제목 찾기<input type="search" aria-label="원고 회차·제목 검색" placeholder="예: 120화 또는 제목" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /></label>
    <p className="list-summary" role="status">{query ? `검색 결과 ${filtered.length}편` : `전체 ${documents.length}편`}{visible.length ? ` · ${currentPage*PAGE_SIZE+1}–${currentPage*PAGE_SIZE+visible.length}번째 표시` : ''}</p>
    {pageCount>1 && <nav className="list-pagination" aria-label="원고 목록 페이지"><button type="button" aria-label="원고 이전 페이지" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}><ChevronLeft size={16}/></button><span>{currentPage+1} / {pageCount}</span><button type="button" aria-label="원고 다음 페이지" disabled={currentPage===pageCount-1} onClick={()=>setPage(currentPage+1)}><ChevronRight size={16}/></button></nav>}
    <div className="document-picker" aria-label="원고 목록">{visible.map(doc => <button type="button" className={doc.id===selectedId?'selected':''} aria-current={doc.id===selectedId?'true':undefined} key={doc.id} onClick={()=>{localSelection.current=doc.id;onSelect(doc.id);}}><FileText size={18}/><span><strong>{doc.chapter_index+1}화 · {doc.title}</strong><small>{doc.analysis_status==='analyzed'?'분석 완료':doc.analysis_status==='stale'?'수정 후 재분석 필요':'아직 분석하지 않음'}</small></span></button>)}</div>
    {!visible.length && <div className="list-empty"><p>{documents.length ? '검색한 회차나 제목이 없습니다.' : '아직 가져온 원고가 없습니다.'}</p>{query && <button onClick={()=>{setQuery('');setPage(0);}}>검색 지우기</button>}</div>}

  </div>;
}
