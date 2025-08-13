import React, { useState,useRef } from 'react';
import ProjectNameInput from '../Inputs/ProjectNameInput';
import MicrophoneSelect from '../Inputs/MicrophoneSelect';
import ProjectLocationInput from '../Inputs/ProjectLocationInput';
import '../../assets/css/SettingsForm.css';
import folderIcon from '../../assets/images/folder.svg';

interface SettingsFormProps {
  onClose: () => void;
}

const SettingsForm: React.FC<SettingsFormProps> = ({ onClose }) => {
  const [projectName, setProjectName] = useState('Fourth Grade Math 2025-06-26');
  const [selectedMicrophone, setSelectedMicrophone] = useState('IP Microphone');
  const [projectLocation, setProjectLocation] = useState('/live/stream');
  // const directoryInputRef = useRef<HTMLInputElement>(null);

  // const handleIconClick = () => {
  //   if (directoryInputRef.current) {
  //     directoryInputRef.current.click();
  //   }
  // };

  // const handleDirectoryChange = (event: React.ChangeEvent<HTMLInputElement>) => {
  //   const files = event.target.files;
  //   if (files && files.length > 0) {
  //     // Extract the directory name from the first file's webkitRelativePath
  //     const fullPath = files[0].webkitRelativePath;
  //     const directoryName = fullPath.split('/')[0]; // Get the directory name
  //     setProjectLocation(directoryName); // Update the project location state
  //   }
  // };

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
              // onClick={handleIconClick}
              title="Click to select a directory path"
            />
            <input
              type="file"
              // ref={directoryInputRef}
              style={{ display: 'none' }}
              // onChange={handleDirectoryChange}
              // webkitdirectory="true" // Pass as a string
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
