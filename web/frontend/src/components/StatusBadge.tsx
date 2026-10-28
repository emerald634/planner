import { syncLabels } from '../lib/format'
import type { Lead } from '../types'
import { Badge } from './WorkspaceUI'

export function StatusBadge({ status }: { status: Lead['sync_status'] }) {
  return <Badge className={`badge-${status}`}><i />{syncLabels[status]}</Badge>
}

