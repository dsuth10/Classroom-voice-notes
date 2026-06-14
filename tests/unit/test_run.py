from unittest import mock

@mock.patch("run.QApplication")
@mock.patch("run.SettingsManager")
@mock.patch("run.prompt_first_launch_vault_picker")
@mock.patch("run.AppController")
@mock.patch("run.RecordingIndicator")
@mock.patch("run.MainWindow")
def test_run_main(mock_main_window, mock_indicator, mock_controller, mock_prompt, mock_settings, mock_qapp):
    import run
    
    # Setup mock returns
    mock_prompt.return_value = "C:/TestVault"
    mock_settings_inst = mock.MagicMock()
    mock_settings.return_value = mock_settings_inst
    
    mock_controller_inst = mock.MagicMock()
    mock_controller_inst.state = "IDLE_LISTENING"
    mock_controller.return_value = mock_controller_inst
    
    mock_indicator_inst = mock.MagicMock()
    mock_indicator.return_value = mock_indicator_inst
    
    mock_window_inst = mock.MagicMock()
    mock_main_window.return_value = mock_window_inst
    
    # Run main
    with mock.patch("sys.exit") as mock_exit:
        run.main()
        
        # Verify instantiation
        mock_qapp.assert_called_once()
        mock_settings.assert_called_once()
        mock_prompt.assert_called_once_with(mock_settings_inst)
        mock_controller.assert_called_once_with(mock_settings_inst)
        mock_indicator.assert_called_once()
        mock_main_window.assert_called_once_with(mock_settings_inst, mock_controller_inst)
        
        # Verify signal connections
        mock_controller_inst.state_changed.connect.assert_called_with(mock_indicator_inst.set_state)
        mock_controller_inst.recording_time_updated.connect.assert_called_with(mock_indicator_inst.update_recording_time)
        mock_indicator_inst.set_state.assert_called_with("IDLE_LISTENING")
        mock_indicator_inst.show.assert_called_once()
        mock_window_inst.show.assert_called_once()
        
        # Verify execution
        mock_exit.assert_called_once()
