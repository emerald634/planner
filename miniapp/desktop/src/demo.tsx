import { createRoot } from 'react-dom/client';
import './theme.css';

const local = ['127.0.0.1', 'localhost'].includes(location.hostname);
if (import.meta.env.DEV && import.meta.env.MODE === 'desktop-demo' && local) {
  // This import is reachable only through dev-only demo.html, never index.html.
  import('./App').then(({ default: App }) => createRoot(document.getElementById('root')!).render(<App />));
} else {
  document.getElementById('root')!.textContent = 'Демонстрация доступна только в изолированном локальном режиме.';
}
