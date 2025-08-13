import React, { useState } from 'react';
import RecordingButton from '../Buttons/RecordingButton';
import UploadButton from '../Buttons/UploadButton';
import NotificationsDisplay from '../Display/NotificationsDisplay';
import ProjectNameDisplay from '../Display/ProjectNameDisplay';
import WelcomeModal from '../Modals/WelcomeModal';
import '../../assets/css/HeaderBar.css';

const HeaderBar: React.FC = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [notification, setNotification] = useState('Start recording or upload an audio file to begin a new session');
  const [projectName, setProjectName] = useState('Fourth Grade Math 2025-06-26');
  const [selectedMicrophone, setSelectedMicrophone] = useState('default');
  const [projectLocation, setProjectLocation] = useState('');
  const [isWelcomeOpen, setIsWelcomeOpen] = useState(false);

  const handleRecordingToggle = () => {
    setIsRecording(!isRecording);
    setNotification(isRecording ? 'Start recording or upload an audio file to begin a new session' : 'Stop recording to get AI summary');
  };

  const handleFileUpload = (file: File) => {
    setNotification('Stop recording to get AI summary');
    console.log('File Uploaded:', file);
  };

  return (
    <div className="header-bar">
      <RecordingButton isRecording={isRecording} onClick={handleRecordingToggle} />
      <UploadButton onUpload={handleFileUpload} disabled={isRecording} />
      <NotificationsDisplay notification={notification} />
      <ProjectNameDisplay projectName={projectName} />
      <WelcomeModal
        isOpen={isWelcomeOpen}
        onClose={() => setIsWelcomeOpen(false)}
        projectName={projectName}
        setProjectName={setProjectName}
        selectedMicrophone={selectedMicrophone}
        setSelectedMicrophone={setSelectedMicrophone}
        projectLocation={projectLocation}
        setProjectLocation={setProjectLocation}
      />
    </div>
  );
};

export default HeaderBar;