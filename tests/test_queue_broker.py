import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from bitrix import Lead
from distribution import best_distributions
from planner.distribution_queue import MOSCOW, DistributionQueue
from planner.queue_broker import BrokerError, BrokerQueue


class BrokerClientTests(unittest.TestCase):
    def test_purpose_author_and_no_secret_error(self):
        calls = []

        def handle(r):
            calls.append(r)
            return httpx.Response(200, json={"ready": True})

        with httpx.Client(
            base_url="http://writer", transport=httpx.MockTransport(handle)
        ) as c:
            broker = BrokerQueue("/not-used", "test-service-key", 123, c)
            broker.initialize()
            self.assertEqual(
                calls[0].headers["authorization"], "Bearer test-service-key"
            )
            self.assertIn(b'"actor_id":123', calls[0].content)
        with httpx.Client(
            base_url="http://writer",
            transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        ) as c:
            with self.assertRaises(BrokerError) as error:
                BrokerQueue("/not-used", "private-value", 123, c).initialize()
            self.assertNotIn("private-value", str(error.exception))


class BotBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_handler_broker_mode_never_opens_local_writer(self):
        from bot import confirm_distribution

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = root / "bot.key"
            key.write_text("x" * 43, encoding="ascii")
            key.chmod(0o600)
            queue = DistributionQueue(root / "queue.db")
            calls = []

            class Remote:
                def __init__(self, *args):
                    calls.append("remote")

                def initialize(self):
                    queue.initialize()

                def find(self, i):
                    return queue.find(i)

                def publish(self, s, ids):
                    calls.append("publish")
                    return queue.publish(s, ids)

                def close(self):
                    pass

            day = datetime.now(MOSCOW).date() - timedelta(days=1)
            data = {
                "stage_ids": ("IN_PROCESS",),
                "variants": best_distributions({day: 1}, ["Synthetic manager"]),
                "variant_index": 0,
                "selected": [0],
                "distribution_session": str(uuid4()),
            }
            config = SimpleNamespace(
                distribution_confirmer_ids={123},
                distribution_queue_path=None,
                queue_writer_socket=root / "writer.sock",
                queue_writer_key_file=key,
                manager_names=("Synthetic manager",),
                manager_telegram_ids=(8306778724,),
                planner_active_manager_ids={8306778724},
            )
            callback = SimpleNamespace(
                from_user=SimpleNamespace(id=123),
                answer=AsyncMock(),
                message=SimpleNamespace(answer=AsyncMock()),
            )
            state = SimpleNamespace(get_data=AsyncMock(return_value=data))
            crm = SimpleNamespace(
                get_leads=AsyncMock(
                    return_value=[
                        Lead(
                            1,
                            datetime(day.year, day.month, day.day, 12, tzinfo=MOSCOW),
                            "IN_PROCESS",
                        )
                    ]
                )
            )
            with (
                patch("planner.queue_broker.BrokerQueue", Remote),
                patch(
                    "bot.DistributionQueue",
                    side_effect=AssertionError("Unsafe local fallback"),
                ),
            ):
                await confirm_distribution(callback, state, config, crm)
                await confirm_distribution(callback, state, config, crm)
            self.assertEqual(calls.count("publish"), 1)
            self.assertEqual(len(list(queue.read())), 1)
