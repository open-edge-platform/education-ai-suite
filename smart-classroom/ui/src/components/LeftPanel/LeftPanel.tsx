import { useState } from "react";
import TranscriptsTab from "../Tabs/TranscriptsTab";
import AISummaryTab from "../Tabs/AISummaryTab";
import "../../assets/css/LeftPanel.css";

const LeftPanel = () => {
  const [activeTab, setActiveTab] = useState<"transcripts" | "summary">("transcripts");

  return (
    <div className="left-panel">
      <div className="tabs">
        <button
          className={activeTab === "transcripts" ? "active" : ""}
          onClick={() => setActiveTab("transcripts")}
        >
          Transcripts
        </button>
        <button
          className={activeTab === "summary" ? "active" : ""}
          onClick={() => setActiveTab("summary")}
        >
          Summary
        </button>
      </div>
      <div className="tab-content">
        {activeTab === "transcripts" && <TranscriptsTab />}
        {activeTab === "summary" && <AISummaryTab />} 
      </div>
    </div>
  );
};

export default LeftPanel;