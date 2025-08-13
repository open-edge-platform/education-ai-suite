import React from 'react';
import ProjectNameInput from '../Inputs/ProjectNameInput';
import MicrophoneSelect from '../Inputs/MicrophoneSelect';
import ProjectLocationInput from '../Inputs/ProjectLocationInput';
import '../../assets/css/Settings.css';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectName: string;
  setProjectName: (name: string) => void;
  selectedMicrophone: string;
  setSelectedMicrophone: (microphone: string) => void;
  projectLocation: string;
  setProjectLocation: (location: string) => void;
}

const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  projectName,
  setProjectName,
  selectedMicrophone,
  setSelectedMicrophone,
  projectLocation,
  setProjectLocation,
}) => {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h2>Settings</h2>
        <ProjectNameInput projectName={projectName} onChange={setProjectName} />
        <MicrophoneSelect selectedMicrophone={selectedMicrophone} onChange={setSelectedMicrophone} />
        <ProjectLocationInput projectLocation={projectLocation} onChange={setProjectLocation} />
        <button onClick={onClose} className="close-button">Close</button>
      </div>
    </div>
  );
};

export default SettingsModal;