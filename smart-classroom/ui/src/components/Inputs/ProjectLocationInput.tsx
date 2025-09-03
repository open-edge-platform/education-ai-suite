import React from 'react';

interface ProjectLocationInputProps {
  projectLocation: string;
  onChange: (location: string) => void;
  placeholder?: string;
}

const ProjectLocationInput: React.FC<ProjectLocationInputProps> = ({
  projectLocation,
  onChange,
  placeholder = "Select project folder",
}) => {
  return (
    <input
      type="text"
      value={projectLocation}
      onChange={(e) => onChange(e.target.value)}
      id="projectLocation"
      placeholder={placeholder}
      style={{ background: "#f8f8f8" }}
    />
  );
};

export default ProjectLocationInput;