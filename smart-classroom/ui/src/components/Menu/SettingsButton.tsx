import React from 'react';
import Modal from '../Modals/Modal';
import SettingsForm from '../Modals/SettingsForm';

interface SettingsButtonProps {
  isOpen: boolean;
  onClose: () => void;
  projectName: string;
  setProjectName: (name: string) => void;
  selectedMicrophone: string;
  setSelectedMicrophone: (microphone: string) => void;
  projectLocation: string;
  setProjectLocation: (location: string) => void;
}

const SettingsButton: React.FC<SettingsButtonProps> = ({
  isOpen,
  onClose,
  projectName,
  setProjectName,
  selectedMicrophone,
  setSelectedMicrophone,
  projectLocation,
  setProjectLocation,
}) => {
  return (
    <Modal isOpen={isOpen} onClose={onClose}>
      <SettingsForm
        onClose={onClose}
        projectName={projectName}
        setProjectName={setProjectName}
        selectedMicrophone={selectedMicrophone}
        setSelectedMicrophone={setSelectedMicrophone}
        projectLocation={projectLocation}
        setProjectLocation={setProjectLocation}
      />
    </Modal>
  );
};

export default SettingsButton;