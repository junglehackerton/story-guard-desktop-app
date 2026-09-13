import type { AnalysisJob } from './types';

export function belongsToNewAnalysis(job: AnalysisJob, baseline: { projectId: number; jobId: number } | null) {
  return !baseline || job.project_id !== baseline.projectId || job.id > baseline.jobId;
}

/** A transport failure must not reuse a previous run's completion as success. */
export function analysisJobAfterError(job: AnalysisJob | null, baseline: {projectId: number; jobId: number}) {
  return job && job.project_id === baseline.projectId && belongsToNewAnalysis(job, baseline) ? job : null;
}

type AnalysisRequest = {model?: string; effort?: string; force?: boolean; range?: {startChapter: number | null; endChapter: number | null}};

export function analysisRetryRequest(job: AnalysisJob, fallback: AnalysisRequest | null) {
  const saved = job.review_context;
  if (saved?.model) return {model: saved.model, effort: saved.effort ?? undefined, force: false,
    range: {startChapter: saved.start_chapter ?? null, endChapter: saved.end_chapter ?? null}};
  return fallback ? {...fallback, force: false} : null;
}
