import { useId, useState } from 'react';
import type { StorySetting } from '../lib/types';

type SettingValues = Pick<StorySetting, 'title' | 'content' | 'certainty'>;
export function StorySettingForm({ initial, onSave, onCancel, disabled = false }: {
  initial?: SettingValues;
  onSave: (values: SettingValues) => Promise<boolean>;
  onCancel?: () => void;
  disabled?: boolean;
}) {
  const [title, setTitle] = useState(initial?.title ?? '');
  const [content, setContent] = useState(initial?.content ?? '');
  const [certainty, setCertainty] = useState<StorySetting['certainty']>(initial?.certainty ?? 'draft');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const errorId = useId();
  const editing = Boolean(initial);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saving || disabled || !title.trim() || !content.trim()) return;
    setSaving(true); setError('');
    try {
      if (!await onSave({ title: title.trim(), content: content.trim(), certainty })) throw new Error('save failed');
      if (!editing) { setTitle(''); setContent(''); setCertainty('draft'); }
    } catch {
      setError('설정 메모를 저장하지 못했습니다. 입력 내용은 유지했으니 다시 시도해 주세요.');
    } finally { setSaving(false); }
  }
  return <form className="setting-form" onSubmit={submit} aria-busy={saving} aria-describedby={error ? errorId : undefined}>
    <fieldset disabled={saving || disabled}>
      <label>설정 제목<input aria-label={editing ? '설정 제목 편집' : '설정 제목'} required value={title} onChange={event => setTitle(event.target.value)} placeholder="예: 봉인검 사용 조건" /></label>
      <label>설정 내용<textarea aria-label={editing ? '설정 내용 편집' : '설정 내용'} required value={content} onChange={event => setContent(event.target.value)} placeholder="작품의 규칙이나 세계관 메모를 입력하세요" /></label>
      <label>설정 구분<select aria-label={editing ? '설정 상태 편집' : '설정 상태'} value={certainty} onChange={event => setCertainty(event.target.value as StorySetting['certainty'])}><option value="confirmed">확정 설정</option><option value="draft">구상 메모</option></select></label>
      <div className="setting-form-actions"><button className="primary" type="submit" disabled={!title.trim() || !content.trim()}>{saving ? '저장 중…' : editing ? '저장' : '설정 추가'}</button>{onCancel && <button type="button" onClick={onCancel}>취소</button>}</div>
    </fieldset>
    {error && <p className="form-error" id={errorId} role="alert">{error}</p>}
  </form>;
}
