"""Bounded timeout splitting with durable successful leaves and sibling isolation."""

import time


def response_timed_out(error):
    # Only the provider response deadline benefits from reducing the work.
    # Connection setup, quota, validation and cancellation are separate failures.
    message = str(error).lower()
    # Keep provider wording differences from bypassing the bounded split path.
    # Transport errors are intentionally handled separately by gpt_analyzer.
    return any(marker in message for marker in (
        'gpt 응답 대기 시간이 초과되었습니다',
        '응답 시간이 초과',
        'response timed out',
        'request timed out',
        'read timeout',
        'deadline exceeded',
        'timed out',
    ))


def review_window(run, index, chunk_ids, evaluate, cancelled, max_seconds=180):
    results, errors = [], []
    # A timeout-splitting tree can otherwise spend 45 seconds on every leaf
    # before the caller gets a chance to isolate the bad window. Bound the
    # whole window so a single provider stall cannot block the manuscript.
    deadline = time.monotonic() + max_seconds

    def visit(ids, path='', depth=0, neighbors=()):
        if cancelled():
            raise RuntimeError('GPT 분석이 취소되었습니다.')
        if time.monotonic() >= deadline:
            errors.append(f"세부 구간 {path or '전체'} (청크 {ids[0]}–{ids[-1]}): GPT 구간 처리 상한 {max_seconds}초를 초과했습니다.")
            return
        checkpoint = run.get_part(index, path)
        if not checkpoint or not checkpoint.get('split'):
            try:
                result, evidence_ids, reused = evaluate(ids, neighbors, path, checkpoint)
                run.save_part(index, path, result.model_dump_json(), evidence_ids, ids, reused)
                results.append((result, evidence_ids, ids, reused))
                return
            except Exception as error:
                if cancelled() or '원고가 변경' in str(error) or '취소' in str(error):
                    raise
                run.discard_part(index, path)
                can_split = (response_timed_out(error) or getattr(error, 'code', None) == 'context_length') and len(ids) > 2 and depth < 2
                run.part_status(index, path, ids, 'split' if can_split else 'failed', str(error)[:500],
                                error_code=getattr(error, 'code', None))
                if getattr(error, 'stop_run', False):
                    raise
                if not can_split:
                    errors.append(f"세부 구간 {path or '전체'} (청크 {ids[0]}–{ids[-1]}): {error}")
                    return
                run.split_part(index, path)
        midpoint = len(ids) // 2
        # Include one neighboring chunk as context across each cut, without
        # assigning its ownership twice. Retrieval still supplies distant evidence.
        visit(ids[:midpoint], path + 'L', depth + 1, (*neighbors, ids[midpoint]))
        visit(ids[midpoint:], path + 'R', depth + 1, (*neighbors, ids[midpoint - 1]))

    visit(chunk_ids)
    return results, errors
