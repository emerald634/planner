import { Redirect, Route, Switch, useLocation, useSearch } from 'wouter'
import { useAuth } from './auth/AuthContext'
import { ForegroundVisit } from './auth/ForegroundVisit'
import { Layout } from './components/Layout'
import { DashboardPage } from './pages/DashboardPage'
import { LeadDetailPage } from './pages/LeadDetailPage'
import { LeadsPage } from './pages/LeadsPage'
import { LoginPage } from './pages/LoginPage'
import { StatisticsPage } from './pages/StatisticsPage'
import { EmployeesPage, SettingsPage } from './pages/WorkspacePages'
import { DistributionsPage } from './planner/DistributionsPage'
import { PlannerPage } from './planner/PlannerPage'
import { plannerRoutes, type PlannerView } from './planner/navigation'
import { PlannerAccessGate, PlannerAccessProvider } from './planner/PlannerAccess'

function Guard() {
  const { user, loading } = useAuth()
  const [location] = useLocation()
  const search = useSearch()
  if (loading) return <div className="splash">Рабочее пространство</div>
  if (!user) return <Redirect to="/login" replace />
  const enabled = import.meta.env.VITE_WORKSPACE_ENABLED !== '0'
  const query = new URLSearchParams(search)
  const legacyView = query.get('view') as PlannerView | null
  if (enabled && location === '/planner' && legacyView && Object.hasOwn(plannerRoutes, legacyView)) {
    query.delete('view')
    return <Redirect to={plannerRoutes[legacyView] + (query.size ? '?' + query.toString() : '')} replace />
  }
  return <PlannerAccessProvider key={`${user.id}:${user.role}`}><ForegroundVisit /><Layout><Switch>
    <Route path="/" component={DashboardPage} />
    <Route path="/leads" component={LeadsPage} /><Route path="/leads/:id" component={LeadDetailPage} />
    <Route path="/managers" component={EmployeesPage} /><Route path="/statistics" component={StatisticsPage} /><Route path="/settings" component={SettingsPage} />
    {enabled && <Route path="/distributions"><PlannerAccessGate><DistributionsPage /></PlannerAccessGate></Route>}
    {enabled && ['/planner','/planner/tasks','/planner/approvals','/planner/history','/planner/reports'].map(path => <Route key={path} path={path}><PlannerAccessGate><PlannerPage /></PlannerAccessGate></Route>)}
    <Route><Redirect to="/" replace /></Route>
  </Switch></Layout></PlannerAccessProvider>
}
export default function App() {
  return <Switch><Route path="/login" component={LoginPage} /><Route><Guard /></Route></Switch>
}
