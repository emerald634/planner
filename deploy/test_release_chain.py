"""Post-install isolated test: artificial distribution, temporary DBs, no CRM."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from planner.distribution_queue import DistributionQueue, MOSCOW
from planner.store import Store
from planner.sync import sync_once

with TemporaryDirectory(prefix='planner-release-test-') as directory:
    root = Path(directory)
    now = datetime.now(MOSCOW)
    allocations = []
    for n, (tg, bx, name) in enumerate(((8306778724, 460, 'Вячеслав'), (7939114214, 110, 'Яна')), 1):
        day = (now.date() - timedelta(days=n)).isoformat()
        allocations.append({'telegram_id': tg, 'bitrix_id': bx, 'name': name, 'dates': [day], 'count': 1, 'leads': [{'id': n, 'created_date': day, 'stage_id': 'IN_PROCESS'}]})
    value = {'schema': 1, 'distribution_id': str(uuid4()), 'workday': now.date().isoformat(), 'confirmed_at': now.isoformat(), 'confirmed_by': 8306778724, 'variant_index': 1, 'variant_id': 'isolated-test-variant', 'stage_id': 'IN_PROCESS', 'allocations': allocations, 'total': 2}
    queue = DistributionQueue(root / 'queue.db')
    queue.initialize()
    queue.publish(value, {8306778724})
    store = Store(root / 'planner.db')
    store.initialize()
    sync_once(store, queue.path, {8306778724})
    sync_once(Store(store.path), queue.path, {8306778724})
    for allocation in allocations:
        actor = store.actor(allocation['telegram_id'])
        plan = store.list_plans(actor)[0]
        approved = store.confirm_plan(actor, plan['id'])
        task = approved['tasks'][0]
        store.timer(actor, task['id'], 'start')
        task = store.timer(actor, task['id'], 'stop')
        store.patch_task(actor, task['id'], {'revision': task['revision'], 'actual_value': 1, 'result': 'Тестовый результат', 'comment': 'Искусственные данные', 'status': 'done'})
        report = store.close_plan(actor, plan['id'])
        assert report['tasks'][0]['actual_value'] == 1
    assert len(store.list_plans(store.actor(1073597301))) == 2
    print('PASS: isolated queue/import/manager confirmation/execution/reports/restart; no production DB or CRM')
