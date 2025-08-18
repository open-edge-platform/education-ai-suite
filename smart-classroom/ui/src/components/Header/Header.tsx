import React, { useState, useEffect } from 'react';
import NotificationsDisplay from '../Display/NotificationsDisplay';
import ProjectNameDisplay from '../Display/ProjectNameDisplay';
import '../../assets/css/HeaderBar.css';
import recordON from '../../assets/images/recording-on.svg';
import recordOFF from '../../assets/images/recording-off.svg';
import sideRecordIcon from '../../assets/images/sideRecord.svg';

const HeaderBar: React.FC = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [notification, setNotification] = useState('Start recording or upload an audio file to begin a new session');
  const [projectName, setProjectName] = useState('Fourth Grade Math 2025-06-26');
  const [timer, setTimer] = useState(0);

useEffect(() => {
  let interval: number | null = null;
  if (isRecording) {
    interval = window.setInterval(() => {
      setTimer((prevTimer) => prevTimer + 1);
    }, 1000);
  } else if (!isRecording && timer !== 0) {
    if (interval !== null) {
      clearInterval(interval);
    }
  }
  return () => {
    if (interval !== null) {
      clearInterval(interval);
    }
  };
}, [isRecording, timer]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  };

  const handleRecordingToggle = () => {
    setIsRecording(!isRecording);
    setNotification(
      isRecording ? 'Start recording or upload an audio file to begin a new session' : 'Stop recording to get AI summary'
    );
    if (!isRecording) {
      setTimer(0); 
    }
  };

  const handleFileUpload = (file: File) => {
    setNotification('Stop recording to get AI summary');
    console.log('File Uploaded:', file);
  };

  return (
    <div className="header-bar">
      <div className="navbar-left">
        <img
          src={isRecording ? recordON : recordOFF}
          alt="Record Icon"
          className="record-icon"
          onClick={handleRecordingToggle}
        />
        {isRecording ? (
          <span className="timer">{formatTime(timer)}</span>
        ) : (
          <img src={sideRecordIcon} alt="Side Record Icon" className="side-record-icon" />
        )}
        <button className="text-button" onClick={handleRecordingToggle} title={isRecording ? 'Stop Recording' : 'Start Recording'}>
          <span>{isRecording ? 'Stop Recording' : 'Start Recording'}</span>
        </button>
        <button className="text-button" onClick={() => document.getElementById('fileInput')?.click()} disabled={isRecording} 
          title="Upload audio">
          Upload File
        </button>
        <input
          type="file"
          id="fileInput"
          accept="audio/*"
          style={{ display: 'none' }}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) handleFileUpload(file);
          }}
        />
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