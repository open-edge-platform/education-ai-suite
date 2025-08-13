import React from 'react';

interface ProjectNameInputProps {
  projectName: string;
  onChange: (name: string) => void;
}

const ProjectNameInput: React.FC<ProjectNameInputProps> = ({ projectName, onChange }) => {
  return (
    <div>
      <label htmlFor="project-name">Project Name:</label>
      <input
        type="text"
        id="project-name"
        value={projectName}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
};

export default ProjectNameInput;