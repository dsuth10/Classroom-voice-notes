# app/destinations/outbox_worker.py
from PySide6.QtCore import QThread, Signal

class OutboxWorker(QThread):
    finished = Signal(int, int)  # sent_count, reconciled_count

    def __init__(self, dispatcher) -> None:
        super().__init__()
        self.dispatcher = dispatcher
        self.manual = False

    def run(self) -> None:
        try:
            sent = self.dispatcher.retry_pending(manual=self.manual)
            reconciled = self.dispatcher.reconcile_statuses()
            self.finished.emit(sent, reconciled)
        except Exception:
            self.finished.emit(0, 0)
