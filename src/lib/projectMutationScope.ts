/** Scope write results to one visit, independently of read/retry counters. */
export class ProjectMutationScope {
  private visit = { projectId: null as number | null };
  private pending = new Set<string>();

  activate(projectId: number | null) {
    if (this.visit.projectId !== projectId) this.visit = { projectId };
  }

  begin(projectId: number, resource: string) {
    const visit = this.visit;
    const key = `${projectId}/${resource}`;
    if (visit.projectId !== projectId || this.pending.has(key)) return null;
    this.pending.add(key);
    return {
      isCurrent: () => this.visit === visit,
      finish: () => this.pending.delete(key),
    };
  }
}
