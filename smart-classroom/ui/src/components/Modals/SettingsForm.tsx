import React, { useState } from 'react';
import ProjectNameInput from '../Inputs/ProjectNameInput';
import MicrophoneSelect from '../Inputs/MicrophoneSelect';
import ProjectLocationInput from '../Inputs/ProjectLocationInput';
import '../../assets/css/SettingsForm.css';
import folderIcon from '../../assets/images/folder.svg';
import { constants } from '../../../public/constants';

interface SettingsFormProps {
  onClose: () => void;
  projectName: string;
  setProjectName: (name: string) => void;
}

const SettingsForm: React.FC<SettingsFormProps> = ({ onClose, projectName, setProjectName }) => {
  const [selectedMicrophone, setSelectedMicrophone] = useState(constants.MICRO_PHONE);
  const [projectLocation, setProjectLocation] = useState('/live/stream');

  return (
    <div className="settings-form">
      <h2>Settings</h2>
      <div className="settings-body">
        <div>
          <label htmlFor="projectName">Project Name</label>
          <ProjectNameInput projectName={projectName} onChange={setProjectName} />
        </div>
        <div>
          <label htmlFor="projectLocation">Project Location</label>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <ProjectLocationInput projectLocation={projectLocation} onChange={setProjectLocation} />
            <img
              src={folderIcon}
              alt="Upload Icon"
              className="upload-icon"
              title="Click to select a directory path"
            />
            <input
              type="file"
              style={{ display: 'none' }}
            />
          </div>
        </div>
        <div>
          <label htmlFor="microphone">Microphone</label>
          <MicrophoneSelect selectedMicrophone={selectedMicrophone} onChange={setSelectedMicrophone} />
        </div>
      </div>
      <div className="button-container">
        <button onClick={onClose} className="submit-button">OK</button>
      </div>
    </div>
  );
};

export default SettingsForm;