import { expect, it } from 'vitest';
import { belongsToNewAnalysis } from './analysisProgress';
import { analysisRetryRequest } from './analysisProgress';
import type { AnalysisJob } from './types';

it('ignores an old completion while a newly requested job is being created', () => {
  const baseline = { projectId: 19, jobId: 92 };
  expect(belongsToNewAnalysis({ id: 92, project_id: 19, status: 'completed' } as AnalysisJob, baseline)).toBe(false);
  expect(belongsToNewAnalysis({ id: 93, project_id: 19, status: 'running' } as AnalysisJob, baseline)).toBe(true);
  expect(belongsToNewAnalysis({ id: 93, project_id: 19, status: 'partial' } as AnalysisJob, baseline)).toBe(true);
});

it('does not turn a failed new request into an older successful result', async () => {
  const { analysisJobAfterError } = await import('./analysisProgress');
  const old = {id:92,project_id:19,status:'completed'} as AnalysisJob;
  expect(analysisJobAfterError(old, {projectId:19,jobId:92})).toBeNull();
});
it('retains a running new job when the request connection fails', async () => {
  const { analysisJobAfterError } = await import('./analysisProgress');
  const running = {id:93,project_id:19,status:'running'} as AnalysisJob;
  expect(analysisJobAfterError(running, {projectId:19,jobId:92})).toBe(running);
});
it('rejects another project status and accepts a current partial result', async () => {
  const { analysisJobAfterError } = await import('./analysisProgress');
  expect(analysisJobAfterError({id:93,project_id:20,status:'failed'} as AnalysisJob, {projectId:19,jobId:92})).toBeNull();
  const partial={id:93,project_id:19,status:'partial'} as AnalysisJob;
  expect(analysisJobAfterError(partial,{projectId:19,jobId:92})).toBe(partial);
});

it('retries the recorded model without replacing its default effort with another selection', () => {
  const job={review_context:{model:'luna',effort:null}} as AnalysisJob;
  expect(analysisRetryRequest(job,{model:'other',effort:'high',force:true})).toEqual({model:'luna',effort:undefined,force:false,range:{startChapter:null,endChapter:null}});
  expect(analysisRetryRequest({review_context:{model:'luna',effort:'medium'}} as AnalysisJob,null)).toEqual({model:'luna',effort:'medium',force:false,range:{startChapter:null,endChapter:null}});
  expect(analysisRetryRequest({} as AnalysisJob,null)).toBeNull();
});
