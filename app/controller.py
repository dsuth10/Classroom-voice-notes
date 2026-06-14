import time
from typing import Any
from PySide6.QtCore import QObject, Signal, QTimer
from app.config.settings import SettingsManager
from app.audit.audit_logger import log_audit_event

from app.audio.input_manager import AudioInputManager

class AppController(QObject):
    state_changed = Signal(str)
    recording_time_updated = Signal(float)
    recording_limit_reached = Signal()
    error_occurred = Signal(str)
    note_saved = Signal(str)
    pipeline_finished = Signal(str)

    def __init__(self, settings_manager: SettingsManager) -> None:
        super().__init__()
        self.settings_manager = settings_manager
        self.state = "IDLE_LISTENING"
        
        self.audio_input_manager = AudioInputManager(self.settings_manager)
        self.audio_input_manager.start()
        
        self.recorder_worker: Any = None
        self.wakeword_worker: Any = None
        self.command_worker: Any = None
        
        self._is_cancelled = False
        
        self.recording_timer = QTimer(self)
        self.recording_timer.setSingleShot(True)
        self.recording_timer.timeout.connect(self._on_recording_timeout)
        
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self._on_elapsed_tick)
        self.elapsed_seconds = 0.0
        
        # Start wake-phrase listening if enabled in settings
        self._start_wake_word_worker()

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
            
        self.note_saved.emit(wav_path)
        self.set_state("IDLE_LISTENING")
        self._start_wake_word_worker()
        self.recorder_worker = None

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

    def reload_settings(self) -> None:
        """Reloads settings and restarts the wake word worker if listening."""
        log_audit_event("SETTINGS_RELOADED", "controller", "Reloading settings from manager")

        if self.state == "IDLE_LISTENING":
            self._stop_wake_word_worker()
            # Defer engine rebuild to after the current Qt event completes
            QTimer.singleShot(0, self._start_wake_word_worker)

    def cleanup(self) -> None:
        """Gracefully stops all background workers and the audio stream. Call before app exit."""
        log_audit_event("CLEANUP", "controller", "Shutting down all workers and audio stream")
        self._stop_timers()
        self._stop_wake_word_worker()
        self._stop_command_worker()
        if self.recorder_worker:
            self.audio_input_manager.unsubscribe(self.recorder_worker.queue)
            self.recorder_worker.stop_recording()
            self.recorder_worker.wait(3000)
            self.recorder_worker = None
        self.audio_input_manager.stop()




