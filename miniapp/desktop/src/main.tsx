import { createRoot } from 'react-dom/client';
import './theme.css';

// Production entry deliberately imports neither the demo application nor fixtures.
createRoot(document.getElementById('root')!).render(
  <main className="entry-gate"><div className="brand-mark">П</div><p className="eyebrow">ПЛАН ДНЯ · DESKTOP</p>
    <h1>Рабочее пространство<br />готовится к запуску</h1>
    <p>Веб-вход пока не подключён. Доступ к планам появится после реализации и проверки защищённой авторизации.</p>
    <span className="badge">Данные сотрудников не загружаются</span>
  </main>,
);
