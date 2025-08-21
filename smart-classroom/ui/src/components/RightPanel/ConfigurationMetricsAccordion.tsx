import React, { useState, useEffect } from "react";
import Accordion from "../common/Accordion";
import "../../assets/css/RightPanel.css"; // Ensure this path is correct

const ConfigurationMetricsAccordion: React.FC = () => {
  const [configData, setConfigData] = useState<any>(null);

  useEffect(() => {
    const fetchConfiguration = async () => {
      try {
        const response = await fetch("../../../public/mockAPI/configuration_metrics.json"); 
        const data = await response.json();
        setConfigData(data);
      } catch (error) {
        console.error("Error fetching configuration data:", error);
      }
    };

    fetchConfiguration();
  }, []);

  return (
    <Accordion title="Configuration & Metrics">
      {configData ? (
        <div className="configuration-metrics">
          <div className="platform-configuration">
            <h3>Platform Configuration</h3>
            <p>Processor: {configData.platform_configuration.processor}</p>
            <p>NPU: {configData.platform_configuration.npu}</p>
            <p>iGPU: {configData.platform_configuration.igpu}</p>
            <p>Memory: {configData.platform_configuration.memory}</p>
            <p>Storage: {configData.platform_configuration.storage}</p>
          </div>
          <div className="software-performance">
            <h3>Software Configuration</h3>
            <p>LLM: {configData.software_configuration.llm}</p>
            <p>ASR: {configData.software_configuration.asr}</p>
            <h3>Performance Metrics</h3>
            <p>TTFT: {configData.performance_metrics.ttft}</p>
            <p>TPOT: {configData.performance_metrics.tpot}</p>
            <p>Total tokens processed: {configData.performance_metrics.total_tokens_processed}</p>
            <p>Time taken to generate summary: {configData.performance_metrics.time_to_generate_summary}</p>
          </div>
        </div>
      ) : (
        <p>Loading configuration data...</p>
      )}
    </Accordion>
  );
};

export default ConfigurationMetricsAccordion;