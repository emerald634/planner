export type Role = 'admin' | 'supervisor' | 'manager'

export interface User {
  id: number
  email: string
  full_name: string
  role: Role
  is_active: boolean
  telegram_chat_id: string | null
  bitrix_user_id: string | null
  work_days: number[]
  workday_start: string
  workday_end: string
  unavailable_until: string | null
  created_at: string
  updated_at: string
}

export interface Lead {
  id: number
  phone: string
  name: string | null
  comment: string | null
  source: string
  manager_id: number | null
  manager: User | null
  transferred_at: string | null
  current_status: string
  sync_status: 'pending' | 'synced' | 'failed' | 'abandoned' | 'local'
  bitrix_lead_id: string | null
  bitrix_deal_id: string | null
  bitrix_lead_status_id: string | null
  bitrix_lead_status_name: string | null
  bitrix_deal_stage_id: string | null
  bitrix_deal_stage_name: string | null
  bitrix_deal_category_id: string | null
  bitrix_deal_stage_semantic: string | null
  last_crm_sync_at: string | null
  sync_attempts: number
  next_crm_retry_at: string | null
  crm_events: CrmStageEvent[]
  sync_error: string | null
  created_at: string
  updated_at: string
}

export interface CrmStageEvent {
  entity_type: 'lead' | 'deal'
  external_id: string
  external_event_id: string
  stage_id: string
  stage_name: string | null
  semantic: string | null
  moved_at: string | null
  created_at: string
}

export interface Source {
  external_id: string
  name: string
  sort: number
}

export interface LeadList {
  items: Lead[]
  total: number
  page: number
  page_size: number
}

export interface Stats {
  total_leads: number
  assigned_leads: number
  pending_sync: number
  managers: number
}
