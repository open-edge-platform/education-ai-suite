import React from 'react';
import Modal from './Modal';
import SettingsForm from './SettingsForm';

interface WelcomeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const WelcomeModal: React.FC<WelcomeModalProps> = ({ isOpen, onClose }) => {
  return (
    <Modal isOpen={isOpen} onClose={onClose}>
      <SettingsForm onClose={onClose} />
    </Modal>
  );
};

export default WelcomeModal;