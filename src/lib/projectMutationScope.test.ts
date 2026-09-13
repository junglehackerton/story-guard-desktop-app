import { expect, it } from 'vitest';
import { ProjectMutationScope } from './projectMutationScope';

it('does not let a previous visit update a different project or a later visit to the same project', () => {
  const scope = new ProjectMutationScope();
  scope.activate(19);
  const old = scope.begin(19, 'issue:54')!;
  expect(old.isCurrent()).toBe(true);
  scope.activate(20);
  expect(old.isCurrent()).toBe(false);
  scope.activate(19);
  expect(old.isCurrent()).toBe(false);
});
it('rejects an old handler attempting to write after project navigation', () => {
  const scope = new ProjectMutationScope(); scope.activate(20);
  expect(scope.begin(19, 'setting:1')).toBeNull();
});
it('allows only one in-flight write per resource and releases it after completion', () => {
  const scope = new ProjectMutationScope(); scope.activate(19);
  const first = scope.begin(19, 'issue:54')!;
  expect(scope.begin(19, 'issue:54')).toBeNull();
  expect(scope.begin(19, 'issue:53')).not.toBeNull();
  first.finish();
  expect(scope.begin(19, 'issue:54')).not.toBeNull();
});
it('does not invalidate writes for a same-project refresh', () => {
  const scope = new ProjectMutationScope(); scope.activate(19);
  const write = scope.begin(19, 'setting:1')!;
  scope.activate(19);
  expect(write.isCurrent()).toBe(true);
});
it('keeps a pending resource locked when leaving and returning to its project', () => {
  const scope = new ProjectMutationScope(); scope.activate(19);
  const old = scope.begin(19, 'issue:54')!;
  scope.activate(20); scope.activate(19);
  expect(scope.begin(19, 'issue:54')).toBeNull();
  old.finish();
  expect(scope.begin(19, 'issue:54')).not.toBeNull();
});
