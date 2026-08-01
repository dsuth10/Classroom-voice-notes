import time
from typing import Any
from PySide6.QtCore import QObject, Signal, QTimer
from app.config.settings import SettingsManager
from app.audit.audit_logger import log_audit_event

from app.audio.input_manager import AudioInputManager
from app.transcription.worker import PipelineWorker

class AppController(QObject):
    state_changed = Signal(str)
    recording_time_updated = Signal(float)
    recording_limit_reached = Signal()
    error_occurred = Signal(str)
    note_saved = Signal(str)
    pipeline_finished = Signal(str)
    audio_level_updated = Signal(float)
    outbox_processed = Signal(int, int)

    def __init__(self, settings_manager: SettingsManager) -> None:
        super().__init__()
        self.settings_manager = settings_manager
        self.state = "IDLE_LISTENING"
        
        self.audio_input_manager = AudioInputManager(self.settings_manager)
        self.audio_input_manager.level_callback = self._on_audio_level
        try:
            self.audio_input_manager.start()
        except Exception as e:
            log_audit_event("MICROPHONE_STREAM_ERROR", "controller", f"Failed to start audio input stream at startup: {e}")
        
        self.recorder_worker: Any = None
        self.wakeword_worker: Any = None
        self.command_worker: Any = None
        self.pipeline_worker: Any = None
        self.outbox_worker: Any = None
        
        self._is_cancelled = False
        
        self.recording_timer = QTimer(self)
        self.recording_timer.setSingleShot(True)
        self.recording_timer.timeout.connect(self._on_recording_timeout)
        
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self._on_elapsed_tick)
        self.elapsed_seconds = 0.0
        
        # Start wake-phrase listening if enabled in settings
        self._start_wake_word_worker()

        # Initialize and start the reminder checking engine
        from app.destinations.reminder_engine import ReminderEngine
        vault_path = self.settings_manager.get("obsidian_vault_path")
        self.reminder_engine = ReminderEngine(vault_path)
        self.reminder_engine.start()

        # Initialize and start the review manager
        from app.destinations.review_manager import ReviewManager
        self.review_manager = ReviewManager(vault_path, self.settings_manager, self.reminder_engine)
        self.review_manager.start()

        # Initialize and start periodic Student Index Rebuilding (every 5 minutes)
        self.index_timer = QTimer(self)
        self.index_timer.timeout.connect(self.rebuild_student_index)
        self.index_timer.start(300000) # 5 minutes in milliseconds
        # Trigger one rebuild shortly after startup in background
        QTimer.singleShot(1000, self.rebuild_student_index)

        # Initialize and start the outbox retry timer (every 60 seconds)
        self.outbox_retry_timer = QTimer(self)
        self.outbox_retry_timer.timeout.connect(lambda: self._retry_pending_outbox(manual=False))
        if self.settings_manager.external_sharing_enabled():
            self.outbox_retry_timer.start(60000)
            # Trigger one outbox check shortly after startup in background
            QTimer.singleShot(2000, lambda: self._retry_pending_outbox(manual=False))

    def set_state(self, new_state: str) -> None:
        old_state = self.state
        self.state = new_state.upper()
        log_audit_event("STATE_TRANSITION", "controller", f"Transitioned from {old_state} to {self.state}")
        self.state_changed.emit(self.state)

    def _start_wake_word_worker(self) -> None:
        if self.wakeword_worker:
            return

        enabled = self.settings_manager.get("wake_word.enabled")
        if not enabled:
            return

        model_path = self.settings_manager.get("wake_word.model_path") or "manual_only"
        phrase = self.settings_manager.get("wake_word.phrase") or "Joshua note"
        threshold = float(self.settings_manager.get("wake_word.threshold") or 0.5)

        # Build engine on the main thread — ONNX Runtime crashes if created inside a QThread on Windows
        from app.wakeword.engine import OpenWakeWordEngine, ManualOnlyEngine, WakeEngine
        try:
            if model_path == "manual_only" or not model_path:
                engine: WakeEngine = ManualOnlyEngine()
            else:
                engine = OpenWakeWordEngine(model_path, threshold=threshold)
        except Exception as e:
            log_audit_event("WAKEWORD_ENGINE_ERROR", "controller", f"Failed to build wake engine: {e}")
            self.error_occurred.emit(f"Wake word engine error: {e}")
            return

        from app.wakeword.worker import WakeWordWorker
        self.wakeword_worker = WakeWordWorker(
            engine=engine,
            phrase=phrase,
            threshold=threshold,
        )
        self.wakeword_worker.wake_word_detected.connect(self._on_wake_word_detected)
        self.wakeword_worker.error_occurred.connect(self._on_wake_word_error)

        self.audio_input_manager.subscribe(self.wakeword_worker.queue)
        self.wakeword_worker.start()

    def _stop_wake_word_worker(self) -> None:
        if not self.wakeword_worker:
            return
        self.audio_input_manager.unsubscribe(self.wakeword_worker.queue)
        self.wakeword_worker.stop_listening()
        self.wakeword_worker.wait()
        self.wakeword_worker = None

    def start_recording(self) -> None:
        if self.state != "IDLE_LISTENING":
            return
        
        self._is_cancelled = False
        
        # Stop wake word listener while recording
        self._stop_wake_word_worker()
        
        self.set_state("RECORDING")
        self.elapsed_seconds = 0.0
        
        # Setup output path
        from app.utils.paths import get_temp_audio_dir
        wav_path = str(get_temp_audio_dir() / f"note_{int(time.time())}.wav")
        
        # Retrieve pre-roll bytes
        pre_roll = self.audio_input_manager.get_pre_roll()
        
        # Instantiate and start RecorderWorker QThread
        from app.audio.worker import RecorderWorker
        self.recorder_worker = RecorderWorker(
            wav_path, pre_roll, sample_rate=self.audio_input_manager.sample_rate
        )
        self.recorder_worker.finished_recording.connect(self._on_recording_finished)
        self.recorder_worker.error_occurred.connect(self._on_recording_error)
        
        self.audio_input_manager.subscribe(self.recorder_worker.queue)
        self.recorder_worker.start()
        
        # Start command listener if enabled in settings
        enabled = self.settings_manager.get("spoken_commands.enabled")
        if enabled:
            model_path = self.settings_manager.get("spoken_commands.model_path")
            keywords = self.settings_manager.get("spoken_commands.grammar_keywords") or ["save", "cancel", "stop", "discard"]
            cooldown = self.settings_manager.get("spoken_commands.command_cooldown_seconds") or 2.0
            
            if model_path:
                from app.commands.worker import VoskCommandWorker
                self.command_worker = VoskCommandWorker(
                    model_path=model_path,
                    keywords=keywords,
                    cooldown_seconds=cooldown
                )
                self.command_worker.command_detected.connect(self._on_command_detected)
                self.command_worker.error_occurred.connect(self._on_command_error)
                
                self.audio_input_manager.subscribe(self.command_worker.queue)
                self.command_worker.start()
        
        # Start limit timers
        limit_seconds = self.settings_manager.get("recording.hard_cap_seconds") or 60
        self.recording_timer.start(int(limit_seconds * 1000))
        self.elapsed_timer.start(1000)  # tick every second

    def stop_and_save(self) -> None:
        if self.state != "RECORDING" or not self.recorder_worker:
            return
        self._stop_timers()
        self._stop_command_worker()
        self.set_state("TRANSCRIBING")
        
        self.audio_input_manager.unsubscribe(self.recorder_worker.queue)
        self.recorder_worker.stop_recording()

    def cancel_recording(self) -> None:
        if self.state != "RECORDING" or not self.recorder_worker:
            return
        self._stop_timers()
        self._stop_command_worker()
        self._is_cancelled = True
        
        self.audio_input_manager.unsubscribe(self.recorder_worker.queue)
        self.recorder_worker.stop_recording()
        
        # Transition back to listening
        self.set_state("IDLE_LISTENING")
        self._start_wake_word_worker()

    def _stop_command_worker(self) -> None:
        if not self.command_worker:
            return
        self.audio_input_manager.unsubscribe(self.command_worker.queue)
        self.command_worker.stop_listening()
        self.command_worker.wait()
        self.command_worker = None

    def _stop_timers(self) -> None:
        self.recording_timer.stop()
        self.elapsed_timer.stop()

    def _on_recording_timeout(self) -> None:
        self.recording_limit_reached.emit()
        self.stop_and_save()

    def _on_recording_finished(self, wav_path: str) -> None:
        import os
        if self._is_cancelled:
            try:
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception as e:
                print(f"Failed to delete cancelled WAV: {e}")
            self.recorder_worker = None
            return

        self.set_state("TRANSCRIBING")
        self.pipeline_worker = PipelineWorker(wav_path, self.settings_manager, self.elapsed_seconds)
        self.pipeline_worker.state_changed.connect(self.set_state)
        self.pipeline_worker.finished_pipeline.connect(self._on_pipeline_finished)
        self.pipeline_worker.reminder_captured.connect(self._on_reminder_captured)
        self.pipeline_worker.error_occurred.connect(self._on_pipeline_error)
        self.pipeline_worker.start()
        self.recorder_worker = None

    def _on_pipeline_finished(self, note_path: str) -> None:
        self.note_saved.emit(note_path)
        self.pipeline_finished.emit(note_path)
        self.set_state("IDLE_LISTENING")
        self._start_wake_word_worker()
        self.pipeline_worker = None

    def _on_reminder_captured(self, classification: dict, note_path: str) -> None:
        reminder_time = classification.get("reminder_time")
        if reminder_time:
            self.reminder_engine.add_reminder(
                title=classification.get("title", "Voice Note Reminder"),
                summary=classification.get("summary", ""),
                reminder_time_str=reminder_time,
                file_path=note_path
            )

    def _on_pipeline_error(self, err_msg: str) -> None:
        self.error_occurred.emit(err_msg)
        self.set_state("ERROR")
        self.set_state("IDLE_LISTENING")
        self._start_wake_word_worker()
        self.pipeline_worker = None

    def _on_recording_error(self, err_msg: str) -> None:
        self.error_occurred.emit(err_msg)
        self.set_state("ERROR")
        self.recorder_worker = None

    def _on_wake_word_detected(self, phrase: str, score: float) -> None:
        log_audit_event("WAKEWORD_TRIGGERED", "controller", f"Wake word '{phrase}' detected score={score}")
        self.start_recording()

    def _on_wake_word_error(self, err_msg: str) -> None:
        self.error_occurred.emit(f"Wake word error: {err_msg}")
        self.set_state("ERROR")

    def _on_command_detected(self, command: str) -> None:
        if command in ("save", "stop"):
            log_audit_event("COMMAND_TRIGGERED_SAVE", "controller", f"Spoken command '{command}' triggered save")
            self.stop_and_save()
        elif command in ("cancel", "discard"):
            log_audit_event("COMMAND_TRIGGERED_CANCEL", "controller", f"Spoken command '{command}' triggered cancel")
            self.cancel_recording()

    def _on_command_error(self, err_msg: str) -> None:
        log_audit_event("COMMAND_ENGINE_ERROR", "controller", f"Vosk command engine error: {err_msg}")

    def _on_elapsed_tick(self) -> None:
        self.elapsed_seconds += 1.0
        self.recording_time_updated.emit(self.elapsed_seconds)

    def _on_audio_level(self, peak_value: float) -> None:
        self.audio_level_updated.emit(peak_value)

    def reload_settings(self) -> None:
        """Reloads settings and restarts the wake word worker if listening."""
        log_audit_event("SETTINGS_RELOADED", "controller", "Reloading settings from manager")

        # Restart the reminder engine in case vault path has changed
        if hasattr(self, 'reminder_engine') and self.reminder_engine:
            self.reminder_engine.stop()
        from app.destinations.reminder_engine import ReminderEngine
        vault_path = self.settings_manager.get("obsidian_vault_path")
        self.reminder_engine = ReminderEngine(vault_path)
        self.reminder_engine.start()

        # Restart the review manager in case vault path or settings changed
        if hasattr(self, 'review_manager') and self.review_manager:
            self.review_manager.stop()
        from app.destinations.review_manager import ReviewManager
        self.review_manager = ReviewManager(vault_path, self.settings_manager, self.reminder_engine)
        self.review_manager.start()

        # Restart AudioInputManager to apply any new device_index configuration
        self.audio_input_manager.stop()
        
        self.audio_input_manager.sample_rate = self.settings_manager.get("audio.sample_rate") or 16000
        self.audio_input_manager.channels = self.settings_manager.get("audio.channels") or 1
        self.audio_input_manager.chunk_size = self.settings_manager.get("audio.chunk_size") or 1280
        device_idx = self.settings_manager.get("audio.device_index")
        self.audio_input_manager.device_index = int(device_idx) if device_idx is not None else None
        
        try:
            self.audio_input_manager.start()
        except Exception as e:
            log_audit_event("MICROPHONE_STREAM_ERROR", "controller", f"Failed to restart audio input stream with new device index: {e}")
            # Try to fall back to default system input device (None)
            try:
                log_audit_event("MICROPHONE_STREAM_FALLBACK", "controller", "Attempting fallback to default system input device")
                self.audio_input_manager.device_index = None
                self.audio_input_manager.start()
            except Exception as fallback_err:
                log_audit_event("MICROPHONE_STREAM_ERROR", "controller", f"Failed fallback to default system input device: {fallback_err}")

        if self.state == "IDLE_LISTENING":
            self._stop_wake_word_worker()
            # Defer engine rebuild to after the current Qt event completes
            QTimer.singleShot(0, self._start_wake_word_worker)

        # Restart or stop the outbox retry timer depending on settings
        if hasattr(self, "outbox_retry_timer") and self.outbox_retry_timer:
            self.outbox_retry_timer.stop()
            if self.settings_manager.external_sharing_enabled():
                self.outbox_retry_timer.start(60000)
                QTimer.singleShot(2000, lambda: self._retry_pending_outbox(manual=False))

    def cleanup(self) -> None:
        """Gracefully stops all background workers and the audio stream. Call before app exit."""
        log_audit_event("CLEANUP", "controller", "Shutting down all workers and audio stream")
        if hasattr(self, 'reminder_engine') and self.reminder_engine:
            self.reminder_engine.stop()
        if hasattr(self, 'review_manager') and self.review_manager:
            self.review_manager.stop()
        if hasattr(self, 'index_timer') and self.index_timer:
            self.index_timer.stop()
        if hasattr(self, 'outbox_retry_timer') and self.outbox_retry_timer:
            self.outbox_retry_timer.stop()
        if self.outbox_worker:
            if self.outbox_worker.isRunning():
                self.outbox_worker.requestInterruption()
                if not self.outbox_worker.wait(17000):
                    log_audit_event(
                        "OUTBOX_WORKER_SHUTDOWN_TIMEOUT",
                        "controller",
                        "Outbox worker did not stop before the shutdown timeout.",
                    )
            if not self.outbox_worker.isRunning():
                self.outbox_worker = None
        self._stop_timers()
        self._stop_wake_word_worker()
        self._stop_command_worker()
        if self.recorder_worker:
            self.audio_input_manager.unsubscribe(self.recorder_worker.queue)
            self.recorder_worker.stop_recording()
            self.recorder_worker.wait(3000)
            self.recorder_worker = None
        self.audio_input_manager.stop()

    def rebuild_student_index(self) -> None:
        """Trigger rebuilding of the local student index."""
        try:
            vault_path = self.settings_manager.get("obsidian_vault_path")
            if not vault_path:
                return
            from app.destinations.student_index import StudentIndexBuilder
            builder = StudentIndexBuilder(vault_path)
            builder.rebuild_index()
        except Exception as e:
            log_audit_event("INDEX_TIMER_TRIGGER_ERROR", "controller", f"Failed to rebuild index: {e}")

    def generate_daily_summary(self) -> None:
        """Trigger daily summary generation for today."""
        try:
            vault_path = self.settings_manager.get("obsidian_vault_path")
            if not vault_path:
                return
            from app.destinations.daily_summary import DailySummaryBuilder
            builder = DailySummaryBuilder(vault_path, self.settings_manager)
            summary_file, telegram_success = builder.generate_daily_summary()
            log_audit_event("DAILY_SUMMARY_TRIGGER_SUCCESS", "controller", f"Generated: {summary_file}, telegram={telegram_success}")
        except Exception as e:
            log_audit_event("DAILY_SUMMARY_TRIGGER_ERROR", "controller", f"Failed to generate summary: {e}")

    def _retry_pending_outbox(self, manual: bool = False) -> None:
        """Starts the background worker to retry sending pending tasks and reconcile statuses."""
        if not self.settings_manager.external_sharing_enabled():
            return
        
        # Prevent starting multiple workers simultaneously
        if self.outbox_worker and self.outbox_worker.isRunning():
            return

        try:
            from app.destinations.external_agent_dispatcher import ExternalAgentDispatcher
            dispatcher = ExternalAgentDispatcher(self.settings_manager)
            
            from app.destinations.outbox_worker import OutboxWorker
            self.outbox_worker = OutboxWorker(dispatcher)
            self.outbox_worker.manual = manual
            self.outbox_worker.processed.connect(self._on_outbox_worker_finished)
            self.outbox_worker.finished.connect(self._on_outbox_thread_finished)
            self.outbox_worker.start()
        except Exception as e:
            log_audit_event("OUTBOX_RETRY_TIMER_ERROR", "controller", f"Failed to start outbox background worker: {e}")

    def _on_outbox_worker_finished(self, sent_count: int, reconciled_count: int) -> None:
        if sent_count > 0 or reconciled_count > 0:
            log_audit_event("OUTBOX_TIMER_COMPLETE", "controller", f"Outbox worker completed. Sent {sent_count}, reconciled {reconciled_count}.")
        self.outbox_processed.emit(sent_count, reconciled_count)

    def _on_outbox_thread_finished(self) -> None:
        worker = self.sender()
        if worker is self.outbox_worker:
            self.outbox_worker = None
        if worker is not None:
            worker.deleteLater()




