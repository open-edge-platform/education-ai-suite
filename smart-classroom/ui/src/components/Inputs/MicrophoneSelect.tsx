import React from 'react';

interface MicrophoneSelectProps {
  selectedMicrophone: string;
  onChange: (microphone: string) => void;
}

const MicrophoneSelect: React.FC<MicrophoneSelectProps> = ({ selectedMicrophone, onChange }) => {
  return (
    <select
      value={selectedMicrophone}
      onChange={(e) => onChange(e.target.value)}
      id="microphone"
    >
      <option value="IP Microphone">IP Microphone</option>
      <option value="Default Microphone">Default Microphone</option>
      {/* Add more options as needed */}
    </select>
  );
};

export default MicrophoneSelect;