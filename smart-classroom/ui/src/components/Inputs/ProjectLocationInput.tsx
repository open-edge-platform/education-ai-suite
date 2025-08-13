import React from 'react';

interface ProjectLocationInputProps {
  projectLocation: string;
  onChange: (location: string) => void;
}

const ProjectLocationInput: React.FC<ProjectLocationInputProps> = ({ projectLocation, onChange }) => {
  return (
    <div>
      <label htmlFor="project-location">Project Location:</label>
      <input
        type="text"
        id="project-location"
        value={projectLocation}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
};

export default ProjectLocationInput;