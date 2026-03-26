/**
 * Global sidebar compact mode events.
 *
 * Distinguishes persisted user preference from temporary page-level requests.
 */

export const SIDEBAR_COMPACT_EVENT = "xagent:sidebar-compact"

export type SidebarCompactReason = "flowdraft-canvas-focus"

export interface SidebarCompactEventDetail {
  reason: SidebarCompactReason
  compact: boolean
}

export function dispatchSidebarCompactEvent(
  detail: SidebarCompactEventDetail
): void {
  if (typeof window === "undefined") {
    return
  }

  window.dispatchEvent(
    new CustomEvent<SidebarCompactEventDetail>(SIDEBAR_COMPACT_EVENT, { detail })
  )
}
