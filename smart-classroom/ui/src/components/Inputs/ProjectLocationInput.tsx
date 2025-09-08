import React from 'react';
import { useTranslation } from 'react-i18next';

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
  return (
    <input
      type="text"
      value={projectLocation}
      onChange={(e) => onChange(e.target.value)}
      id="projectLocation"
      placeholder={effectivePlaceholder}
      style={{ background: "#f8f8f8" }}
    />
  );
};

export default ProjectLocationInput;