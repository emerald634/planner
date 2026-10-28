import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`pw-card ${className}`}>{children}</section>
}
export function Button({ children, secondary, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { secondary?: boolean }) {
  return <button {...props} className={`button ${secondary ? 'button-secondary pw-secondary' : 'button-primary'} ${className}`}>{children}</button>
}
export function Badge({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <span className={`badge ${className}`}>{children}</span>
}
export function LoadingState({ text = 'Загрузка данных…' }: { text?: string }) {
  return <p className="ui-loading" role="status">{text}</p>
}
export function ErrorState({ title, message, retry, retryLabel = 'Повторить загрузку' }: { title: string; message: string; retry?(): void; retryLabel?: string }) {
  return <div className="ui-error" role="alert"><strong>{title}</strong><p>{message}</p>{retry && <Button secondary onClick={retry}>{retryLabel}</Button>}</div>
}
export function Table({ children }: { children: ReactNode }) {
  return <div className="table-wrap"><table>{children}</table></div>
}
export function Modal({ children, onClose, label }: { children: ReactNode; onClose(): void; label: string }) {
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}><section role="dialog" aria-modal="true" aria-label={label}>{children}</section></div>
}
