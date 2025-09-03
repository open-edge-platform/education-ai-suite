import React from 'react';

interface ProjectNameInputProps {
  projectName: string;
  onChange: (name: string) => void; 
  placeholder?: string;
  maxLength?: number;
  autoFocus?: boolean;
}

const ProjectNameInput: React.FC<ProjectNameInputProps> = ({
  projectName,
  onChange,
  placeholder = "Enter project name",
  maxLength = 32,
  autoFocus = false,
}) => {
  return (
    <input
      type="text"
      value={projectName}
      onChange={(e) => onChange(e.target.value)} 
      id="projectName"
      placeholder={placeholder}
      maxLength={maxLength}
      autoFocus={autoFocus}
      style={{ background: "#f8f8f8" }}
    />
  );
};

export default ProjectNameInput;