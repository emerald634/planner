import { createContext, useContext } from 'react'
import type { Me } from './transport'

export type PlannerAccessState =
  | { status: 'not_requested' }
  | { status: 'loading' }
  | { status: 'allowed'; me: Me }
  | { status: 'denied'; message: string }
  | { status: 'error'; kind: 'http' | 'network' | 'invalid'; message: string; httpStatus?: number }
export const PlannerAccessContext = createContext<{ state: PlannerAccessState; retry(): void } | undefined>(undefined)
export function usePlannerAccess() {
  const value = useContext(PlannerAccessContext)
  if (!value) throw new Error('Planner access must use the shared workspace identity boundary')
  return value
}
