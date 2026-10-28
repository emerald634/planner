import { useLocation } from 'wouter'

export type PlannerView = 'home' | 'employees' | 'plan' | 'tasks' | 'requests' | 'history' | 'report' | 'metrics'
export const plannerRoutes: Record<PlannerView, string> = { home: '/', employees: '/managers', plan: '/planner', tasks: '/planner/tasks', requests: '/planner/approvals', history: '/planner/history', report: '/planner/reports', metrics: '/statistics' }
export function usePlannerNavigation() {
  const [location, setLocation] = useLocation()
  const view = (Object.entries(plannerRoutes).find(([, route]) => route === location)?.[0] || 'plan') as PlannerView
  return { view, navigate: (value: PlannerView) => {
    const query = new URLSearchParams(window.location.search)
    query.delete('view')
    setLocation(`${plannerRoutes[value]}${query.size ? '?' + query.toString() : ''}`)
  } }
}
