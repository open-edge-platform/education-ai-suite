import React from 'react';

interface ProjectNameInputProps {
  projectName: string;
  onChange: (name: string) => void; 
}

const ProjectNameInput: React.FC<ProjectNameInputProps> = ({ projectName, onChange }) => {
  return (
    <input
      type="text"
      value={projectName}
      onChange={(e) => onChange(e.target.value)} 
      id="projectName"
    />
  );
};

export default ProjectNameInput;