import { PageHeader } from '../components/PageHeader'
import { LeadFlowSummary } from './DashboardPage'
import { PlannerPage } from '../planner/PlannerPage'
import { PlannerAccessGate } from '../planner/PlannerAccess'
export function StatisticsPage() {
  return <><PageHeader title="Аналитика" subtitle="Показатели из отдельных источников без смешения лидов, задач и звонков" /><LeadFlowSummary distribution />{import.meta.env.VITE_WORKSPACE_ENABLED !== '0' && <PlannerAccessGate embedded><div className="ui-source-heading"><h2>Показатели рабочего дня</h2><span>Источник: Planner · данные телефонии не подключены</span></div><PlannerPage embedded /></PlannerAccessGate>}</>
}
