import React from 'react';

interface MicrophoneSelectProps {
  selectedMicrophone: string;
  onChange: (microphone: string) => void;
}

const MicrophoneSelect: React.FC<MicrophoneSelectProps> = ({ selectedMicrophone, onChange }) => {
  return (
    <div>
      <label htmlFor="microphone-select">Microphone:</label>
      <select
        id="microphone-select"
        value={selectedMicrophone}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="default">Default Microphone</option>
        <option value="external">External Microphone</option>
        {/* Add more options as needed */}
      </select>
    </div>
  );
};

export default MicrophoneSelect;