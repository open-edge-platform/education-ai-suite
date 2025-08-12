import React from 'react';
import '../../assets/css/Settings.css';
interface SettingsProps {
  isOpen: boolean;
  onClose: () => void;
}

const Settings: React.FC<SettingsProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h2>Settings</h2>
        <p>Adjust your application settings here.</p>
        <button onClick={onClose} className="close-button">OK</button>
      </div>
    </div>
  );
};

export default Settings;