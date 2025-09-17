import React from 'react';
import { useTranslation } from 'react-i18next';
import '../../assets/css/ProjectLocationInput.css';

interface ProjectLocationInputProps {
  projectLocation: string;
  onChange: (location: string) => void;
  placeholder?: string;
}

const ProjectLocationInput: React.FC<ProjectLocationInputProps> = ({
  projectLocation,
  onChange,
  placeholder,
}) => {
  const { t } = useTranslation();
  const effectivePlaceholder = placeholder ?? t('settings.projectLocationPlaceholder');
  const suffix = projectLocation.replace(/^storage\//, '');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange('storage/' + e.target.value);
  };

  return (
    <div className="project-location-input">
      <span className="storage-prefix">storage/</span>
      <input
        type="text"
        value={suffix}
        onChange={handleChange}
        id="projectLocation"
        placeholder={effectivePlaceholder}
        className="project-location-field"
      />
    </div>
  );
};

export default ProjectLocationInput;
