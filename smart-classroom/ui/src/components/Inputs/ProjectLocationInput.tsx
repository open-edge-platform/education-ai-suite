import React from 'react';

interface ProjectLocationInputProps {
  projectLocation: string;
  onChange: (location: string) => void;
}

const ProjectLocationInput: React.FC<ProjectLocationInputProps> = ({ projectLocation, onChange }) => {
  return (
    <input
      type="text"
      value={projectLocation}
      onChange={(e) => onChange(e.target.value)}
      id="projectLocation"
    />
  );
};

export default ProjectLocationInput;