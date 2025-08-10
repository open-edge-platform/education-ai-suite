import { useState } from "react";
import TranscriptsTab from "../Tabs/TranscriptsTab";
import AISummaryTab from "../Tabs/AISummaryTab"; // Update the import
import "./LeftPanel.scss";

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
        {activeTab === "summary" && <AISummaryTab />} {/* Update the component */}
      </div>
    </div>
  );
};

export default LeftPanel;