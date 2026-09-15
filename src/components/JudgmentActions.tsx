import { useRef, useState } from 'react';
import type { ContinuityIssue, IssueStatus } from '../lib/types';

export function JudgmentActions({ issue, onSave, onAccepted }: {
  issue: ContinuityIssue;
  onSave: (id: number, status: IssueStatus) => Promise<boolean> | void;
  onAccepted?: () => void;
}) {
  const pending = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  async function save(status: IssueStatus) {
    if (pending.current) return;
    pending.current = true;
    setSaving(true); setError('');
    try {
      if (await onSave(issue.id, status) === false) throw new Error('save failed');
      if (status === 'accepted') onAccepted?.();
    } catch {
      setError('판단 저장을 확인하지 못했습니다. 현재 표시된 판단은 바꾸지 않았습니다. 다시 선택해 저장해 주세요.');
    } finally { pending.current = false; setSaving(false); }
  }
  return <div aria-busy={saving}>
    <div className="judgment-actions">
      {([['accepted', '문제 있음'], ['ignored', '문제 아님'], ['deferred', '판단 보류'], ['open', '확인 대기']] as const).map(([status, label]) =>
        <button key={status} className={issue.status === status ? 'selected' : ''} disabled={saving} onClick={() => void save(status)}>{label}</button>)}
    </div>
    {saving && <p className="muted" role="status">작가 판단을 저장하는 중입니다…</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </div>;
}
