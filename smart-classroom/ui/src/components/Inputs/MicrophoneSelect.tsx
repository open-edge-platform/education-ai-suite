import React from 'react';

interface MicrophoneSelectProps {
  selectedMicrophone: string;
  onChange: (microphone: string) => void;
}

const MicrophoneSelect: React.FC<MicrophoneSelectProps> = ({
  selectedMicrophone,
  onChange
}) => (
  <select
    value={selectedMicrophone || 'IP Microphone'}
    onChange={e => onChange(e.target.value)}
    id="microphone"
    disabled
  >
    <option value="IP Microphone">IP Microphone</option>
  </select>
);

export default MicrophoneSelect;