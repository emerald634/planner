# Backup и rollback

SQLite online backup API, новый O_EXCL файл, integrity/FK/count/fingerprint/закрытые report checks; не cp активного main без journal. Для общей точки согласованно остановить только своих publishers/importer. Auth PG backup/test restore отдельно после разрешения. Secrets backup приватно вне Git/артефактов. Retention/offsite не настроены автоматически.

При сбое сначала сохранить свежие данные/queue/auth и дельту после первого backup. Совместимый recovery factory workspace.application:create_readonly_app не пишет бизнес-данные и не импортирует очередь, оставляет session login/logout/visit. Не выполнять destructive schema downgrade, не стирать новые records восстановлением старого backup поверх текущего.

Старый writable ORM, не знающий sync_status=local, не безопасный rollback. Не менять local→pending: снова откроется CRM export. Возврат bot к direct queue только при остановленном private writer/других publishers, с тем же файлом и одним poller, по отдельному решению. Сохранить оба состояния и согласовать перенос новых данных, не обещать «одной командой без потерь».
