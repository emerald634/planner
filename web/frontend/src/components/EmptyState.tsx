import { Inbox } from 'lucide-react'

export function EmptyState({ text }: { text: string }) {
  return <div className="empty"><span><Inbox size={26} /></span><h3>Пока пусто</h3><p>{text}</p></div>
}

