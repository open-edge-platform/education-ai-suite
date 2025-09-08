import React, { useState, useEffect } from 'react';
import NotificationsDisplay from '../Display/NotificationsDisplay';
import ProjectNameDisplay from '../Display/ProjectNameDisplay';
import '../../assets/css/HeaderBar.css';
import recordON from '../../assets/images/recording-on.svg';
import recordOFF from '../../assets/images/recording-off.svg';
import sideRecordIcon from '../../assets/images/sideRecord.svg';
import { constants } from '../../constants';
import { useAppDispatch, useAppSelector } from '../../redux/hooks';
import { resetFlow, startProcessing, setUploadedAudioPath } from '../../redux/slices/uiSlice';
import { resetTranscript } from '../../redux/slices/transcriptSlice';
import { resetSummary } from '../../redux/slices/summarySlice';
import { useTranslation } from 'react-i18next';
import { uploadAudio } from '../../services/api';


interface HeaderBarProps {
  projectName: string;
  setProjectName: (name: string) => void;
}

const HeaderBar: React.FC<HeaderBarProps> = ({ projectName }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [notification, setNotification] = useState(constants.START_NOTIFICATION);
  const { t } = useTranslation();
  const [timer, setTimer] = useState(0);

  const dispatch = useAppDispatch();
  const isBusy = useAppSelector((s) => s.ui.aiProcessing);
  const summaryEnabled = useAppSelector((s) => s.ui.summaryEnabled);
  const summaryLoading = useAppSelector((s) => s.ui.summaryLoading);
  const transcriptStatus = useAppSelector((s) => s.transcript.status);

  useEffect(() => {
    let interval: number | null = null;
    if (isRecording) {
      interval = window.setInterval(() => setTimer((t) => t + 1), 1000);
    } else if (!isRecording && timer !== 0) {
      if (interval !== null) clearInterval(interval);
    }
    return () => { if (interval !== null) clearInterval(interval); };
  }, [isRecording, timer]);

  useEffect(() => {
    if (summaryEnabled && summaryLoading) setNotification(t('notifications.generatingSummary'));
    else if (summaryEnabled && isBusy && !summaryLoading) setNotification(t('notifications.streamingSummary'));
    else if (isBusy && transcriptStatus === 'streaming') setNotification(t('notifications.loadingTranscript'));
    else if (isBusy && !summaryEnabled) setNotification(t('notifications.analyzingAudio'));
    else if (!isBusy && summaryEnabled) setNotification(t('notifications.summaryReady'));
    else setNotification(t('notifications.start'));
  }, [isBusy, summaryEnabled, summaryLoading, transcriptStatus, t]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  const handleRecordingToggle = () => {
    if (isBusy && !isRecording) return;
    const next = !isRecording;
    setIsRecording(next);

    if (next) {
      setTimer(0);
      setNotification(t('notifications.recording'));
      dispatch(resetFlow());
      dispatch(resetTranscript());
      dispatch(resetSummary());
    } else {
      setNotification(t('notifications.uploading'));
      dispatch(startProcessing());
    }
  };

  const handleFileUpload = async (file: File) => {
    if (isBusy || isRecording) return;
    setNotification(t('notifications.uploading'));
    dispatch(resetFlow());
    dispatch(resetTranscript());
    dispatch(resetSummary());
    dispatch(startProcessing());
    try {
      const result = await uploadAudio(file);
      dispatch(setUploadedAudioPath(result.path)); // <-- Only this, no transcription here
      console.log('File Uploaded:', file.name, 'Saved path:', result.path);
    } catch (e) {
      setNotification('Upload failed');
      console.error('Upload failed', e);
    }
  };

  return (
    <div className="header-bar">
      <div className="navbar-left">
        <img
          src={isRecording ? recordON : recordOFF}
          alt="Record"
          className="record-icon"
          onClick={handleRecordingToggle}
          style={{ opacity: isBusy && !isRecording ? 0.5 : 1, cursor: isBusy && !isRecording ? 'not-allowed' : 'pointer' }}
        />
        <img src={sideRecordIcon} alt="Side Record" className="side-record-icon" />
        <span className="timer">{formatTime(timer)}</span>

        <button
          className="text-button"
          onClick={(e) => { e.preventDefault(); }} 
          disabled={true}
          title="Recording disabled"
          style={{ cursor: 'not-allowed', opacity: 0.6 }}
        >
          {isRecording ? t('header.stopRecording') : t('header.startRecording')}
        </button>

        <label
          className="text-button"
          style={{ opacity: isBusy || isRecording ? 0.6 : 1, cursor: isBusy || isRecording ? 'not-allowed' : 'pointer' }}
        >
          <input
            type="file"
            accept="audio/*"
            style={{ display: 'none' }}
            disabled={isBusy || isRecording}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFileUpload(f);
              e.currentTarget.value = '';
            }}
          />
          {t('header.uploadFile')}
        </label>
      </div>

      <div className="navbar-center">
        <NotificationsDisplay notification={notification} />
      </div>

      <div className="navbar-right">
        <ProjectNameDisplay projectName={projectName} />
      </div>
    </div>
  );
};

export default HeaderBar;