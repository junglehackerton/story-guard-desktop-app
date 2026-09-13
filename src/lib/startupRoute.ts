export type StartupRoute = "projects" | "welcome";

/** Returning writers should land on the shelf; only a clean first run opens the guide. */
export function startupRoute(hasStoredProject: boolean): StartupRoute {
  return hasStoredProject ? "projects" : "welcome";
}
