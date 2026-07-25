from unittest.mock import MagicMock, patch

from app.destinations.outbox_worker import OutboxWorker


def test_outbox_worker_emits_processed_counts() -> None:
    dispatcher = MagicMock()
    dispatcher.retry_pending.return_value = 2
    dispatcher.reconcile_statuses.return_value = 3
    worker = OutboxWorker(dispatcher)
    results: list[tuple[int, int]] = []
    worker.processed.connect(lambda sent, reconciled: results.append((sent, reconciled)))

    worker.run()

    assert results == [(2, 3)]
    retry_kwargs = dispatcher.retry_pending.call_args.kwargs
    reconcile_kwargs = dispatcher.reconcile_statuses.call_args.kwargs
    assert retry_kwargs["manual"] is False
    assert callable(retry_kwargs["should_stop"])
    assert callable(reconcile_kwargs["should_stop"])


def test_outbox_worker_preserves_sent_count_when_reconciliation_fails() -> None:
    dispatcher = MagicMock()
    dispatcher.retry_pending.return_value = 2
    dispatcher.reconcile_statuses.side_effect = RuntimeError("status unavailable")
    worker = OutboxWorker(dispatcher)
    results: list[tuple[int, int]] = []
    worker.processed.connect(lambda sent, reconciled: results.append((sent, reconciled)))

    worker.run()

    assert results == [(2, 0)]


def test_outbox_worker_skips_reconciliation_after_interruption() -> None:
    dispatcher = MagicMock()
    dispatcher.retry_pending.return_value = 1
    worker = OutboxWorker(dispatcher)
    results: list[tuple[int, int]] = []
    worker.processed.connect(lambda sent, reconciled: results.append((sent, reconciled)))

    with patch.object(worker, "isInterruptionRequested", return_value=True):
        worker.run()

    assert results == [(1, 0)]
    dispatcher.reconcile_statuses.assert_not_called()
