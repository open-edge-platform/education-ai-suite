import React, { useState } from 'react';
import ProjectNameInput from '../Inputs/ProjectNameInput';
import MicrophoneSelect from '../Inputs/MicrophoneSelect';
import ProjectLocationInput from '../Inputs/ProjectLocationInput';
import '../../assets/css/SettingsForm.css';
import folderIcon from '../../assets/images/folder.svg';
import { saveSettings, getSettings } from '../../services/api';
import { useTranslation } from 'react-i18next';

interface SettingsFormProps {
  onClose: () => void;
  projectName: string;
  setProjectName: (name: string) => void;
}

const SettingsForm: React.FC<SettingsFormProps> = ({ onClose, projectName, setProjectName }) => {
  const [selectedMicrophone, setSelectedMicrophone] = useState('');
  const [projectLocation, setProjectLocation] = useState('/live/stream');
  const dirInputRef = React.useRef<HTMLInputElement>(null);
  const { t } = useTranslation();

  React.useEffect(() => {
    getSettings().then(s => {
      if (!s) return;
      setProjectName(s.projectName);
      setProjectLocation(s.projectLocation);
      setSelectedMicrophone(s.microphone);
    });
  }, [setProjectName]);

  const openDirectoryPicker = async () => {
    if ('showDirectoryPicker' in window) {
      try {
        // @ts-expect-error: experimental API
        const dir = await window.showDirectoryPicker();
        setProjectLocation(dir.name || '/live/stream');
        return;
      } catch { /* user cancelled */ }
    }
    dirInputRef.current?.click();
  };

  const handleSave = async () => {
    const settings = { projectName, projectLocation, microphone: selectedMicrophone };
    await saveSettings(settings);
    onClose();
  };

  return (
    <div className="settings-form">
      <h2>{t('settings.title')}</h2>
      <div className="settings-body">
        <div>
          <label htmlFor="projectName">{t('settings.projectName')}</label>
          <ProjectNameInput projectName={projectName} onChange={setProjectName} />
        </div>
        <div>
          <label htmlFor="projectLocation">{t('settings.projectLocation')}</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ProjectLocationInput projectLocation={projectLocation} onChange={setProjectLocation} />
            <img
              src={folderIcon}
              alt={t('settings.projectLocation')}
              className="upload-icon"
              title={t('settings.projectLocation')}
              onClick={openDirectoryPicker}
              style={{ cursor: 'pointer' }}
            />
            <input
              ref={dirInputRef}
              type="file"
              style={{ display: 'none' }}
              // @ts-expect-error: non-standard Chromium attribute
              webkitdirectory="true"
              onChange={(e) => {
                const anyFile = e.currentTarget.files?.[0];
                if (anyFile) {
                  const rel = anyFile.webkitRelativePath as string | undefined;
                  if (rel) {
                    const dir = rel.split('/')[0];
                    setProjectLocation('/' + dir);
                  }
                }
                e.currentTarget.value = '';
              }}
            />
          </div>
        </div>
        <div>
          <label htmlFor="microphone">{t('settings.microphone')}</label>
          <MicrophoneSelect selectedMicrophone={selectedMicrophone} onChange={setSelectedMicrophone} />
        </div>
      </div>
      <div className="button-container">
        <button onClick={handleSave} className="submit-button">{t('settings.ok')}</button>
      </div>
    </div>
  );
};

export default SettingsForm;