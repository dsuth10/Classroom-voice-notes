# app/destinations/outbox_worker.py
from PySide6.QtCore import QThread, Signal
from app.destinations.external_agent_dispatcher import ExternalAgentDispatcher

class OutboxWorker(QThread):
    processed = Signal(int, int)  # sent_count, reconciled_count

    def __init__(self, dispatcher: ExternalAgentDispatcher) -> None:
        super().__init__()
        self.dispatcher = dispatcher
        self.manual = False

    def run(self) -> None:
        sent = 0
        try:
            sent = self.dispatcher.retry_pending(
                manual=self.manual,
                should_stop=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                self.processed.emit(sent, 0)
                return
            reconciled = self.dispatcher.reconcile_statuses(
                should_stop=self.isInterruptionRequested,
            )
            self.processed.emit(sent, reconciled)
        except Exception:
            self.processed.emit(sent, 0)
