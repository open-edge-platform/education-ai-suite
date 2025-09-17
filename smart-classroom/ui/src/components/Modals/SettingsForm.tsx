import React, { useState } from 'react';
import ProjectNameInput from '../Inputs/ProjectNameInput';
import MicrophoneSelect from '../Inputs/MicrophoneSelect';
import ProjectLocationInput from '../Inputs/ProjectLocationInput';
import '../../assets/css/SettingsForm.css';
import { saveSettings, getSettings } from '../../services/api';
import { useTranslation } from 'react-i18next';

interface SettingsFormProps {
  onClose: () => void;
  projectName: string;
  setProjectName: (name: string) => void;
}

const SettingsForm: React.FC<SettingsFormProps> = ({ onClose, projectName, setProjectName }) => {
  const [selectedMicrophone, setSelectedMicrophone] = useState('');
  const [projectLocation, setProjectLocation] = useState('storage/');
  const [nameError, setNameError] = useState<string | null>(null);
  const { t } = useTranslation();

  React.useEffect(() => {
    getSettings().then(s => {
      if (!s) return;
      setProjectLocation(s.projectLocation || 'storage/');
      setSelectedMicrophone(s.microphone || '');
    }).catch(() => {});
  }, [setProjectName]);

  const handleSave = async () => {
    if (!projectName.trim()) { 
      setNameError(t('errors.projectNameRequired'));
      return;
    }
    try {
      await saveSettings({ projectName, projectLocation, microphone: selectedMicrophone });
      onClose();
    } catch {}
  };

  const handleNameChange = (name: string) => { 
    setProjectName(name);
    if (nameError) setNameError(null);
  };
  
  return (
    <div className="settings-form">
      <h2>{t('settings.title')}</h2>
      <div className="settings-body">
        <div>
          <label htmlFor="projectName">{t('settings.projectName')}</label>
          <ProjectNameInput projectName={projectName} onChange={handleNameChange} />
          {nameError && (
            <div style={{ color: '#c00', fontSize: 12, marginTop: 4 }}>
              {nameError}
            </div>
          )}
        </div>
        <div>
          <label htmlFor="projectLocation">{t('settings.projectLocation')}</label>
          <ProjectLocationInput 
            projectLocation={projectLocation} 
            onChange={setProjectLocation} 
          />
        </div>
        <div>
          <label htmlFor="microphone">{t('settings.microphone')}</label>
          <MicrophoneSelect 
            selectedMicrophone={selectedMicrophone} 
            onChange={setSelectedMicrophone} 
          />
        </div>
      </div>
      <div className="button-container">
        <button onClick={handleSave} className="submit-button">{t('settings.ok')}</button>
      </div>
    </div>
  );
};

export default SettingsForm;
