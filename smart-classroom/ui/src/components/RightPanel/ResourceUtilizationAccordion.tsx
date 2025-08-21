import React, { useState, useEffect } from 'react';
import { Line } from 'react-chartjs-2';
import { Chart, registerables } from 'chart.js';
import Accordion from '../common/Accordion'; 
import '../../assets/css/RightPanel.css'

Chart.register(...registerables);

const ResourceUtilizationAccordion: React.FC = () => {
  const [resourceData, setResourceData] = useState<any>(null);

  useEffect(() => {
    const fetchResourceData = async () => {
      try {
        const response = await fetch("../../../public/mock-data/metrics.json"); 
        if (!response.ok) {
          throw new Error('Network response was not ok');
        }
        const data = await response.json();
        setResourceData(data);
      } catch (error) {
        console.error('Error fetching resource data:', error);
      }
    };

    fetchResourceData();
  }, []);

const createChartData = (data: any[], label: string) => {
  return {
    labels: data.map(item => {
      const date = new Date(item[0]); 
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit'}); 
    }),
    datasets: [
      {
        label: label,
        data: data.map(item => item[1]), 
        borderColor: 'rgba(73, 166, 216, 1)',
        backgroundColor: 'rgba(250, 251, 254, 0.2)',
      },
    ],
  };
};

  return (
    <Accordion title="Resource Utilization">
      {resourceData ? (
        <div className="accordion-content">
          <div className="chart-row">
            <div className="chart-container">
              <h3>CPU Utilization</h3>
              <Line className="chart" data={createChartData(resourceData.cpu_utilization, 'CPU Utilization')} />
            </div>
            <div className="chart-container">
              <h3>GPU Utilization</h3>
              <Line className="chart" data={createChartData(resourceData.gpu_utilization.map((item: any[]) => [item[0], item[4]]), 'GPU Utilization')} />
            </div>
          </div>
          <div className="chart-row">
            <div className="chart-container">
              <h3>Memory Utilization</h3>
              <Line className="chart" data={createChartData(resourceData.memory.map((item: any[]) => [item[0], item[4]]), 'Memory Utilization')} />
            </div>
            <div className="chart-container">
              <h3>Power Utilization</h3>
              <Line className="chart" data={createChartData(resourceData.power, 'Power Utilization')} />
            </div>
          </div>
        </div>
      ) : (
        <p>Loading resource data...</p>
      )}
    </Accordion>
  );
};

export default ResourceUtilizationAccordion;