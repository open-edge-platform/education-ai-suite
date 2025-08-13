import React from 'react';
import ProjectNameInput from '../Inputs/ProjectNameInput';
interface ProjectNameDisplayProps {
  projectName: string;
}

const ProjectNameDisplay: React.FC<ProjectNameDisplayProps> = ({ projectName }) => {
  return (
    <div className="project-name-display">
      <span>{projectName}</span>
    </div>
  );
};

export default ProjectNameDisplay;