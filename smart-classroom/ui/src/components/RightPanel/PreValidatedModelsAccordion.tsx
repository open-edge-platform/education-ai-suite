import React from "react";
import Accordion from "../common/Accordion";
import "../../assets/css/RightPanel.css"; 

const PreValidatedModelsAccordion: React.FC = () => {
  return (
    <Accordion title="Pre-validated Models">
      <div className="dropdown-container">
        <div className="dropdown-section">
          <h3>Transcripts Model</h3>
          <select className="dropdown">
            <option value="whisper">Whisper</option>
            <option value="model1">Model 1</option>
            <option value="model2">Model 2</option>
          </select>
        </div>
        <div className="dropdown-section">
          <h3>Summary</h3>
          <select className="dropdown">
            <option value="gpt-4">GPT-4</option>
            <option value="model3">Model 3</option>
            <option value="model4">Model 4</option>
          </select>
        </div>
      </div>
    </Accordion>
  );
};

export default PreValidatedModelsAccordion;