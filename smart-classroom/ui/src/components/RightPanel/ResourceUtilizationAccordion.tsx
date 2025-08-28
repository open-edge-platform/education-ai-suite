import React from 'react';
import { Line } from 'react-chartjs-2';
import { Chart, registerables } from 'chart.js';
import Accordion from '../common/Accordion'; 
import '../../assets/css/RightPanel.css'
import resourceData from '../../mock-data/metrics.json';
import { useTranslation } from 'react-i18next';
Chart.register(...registerables);

const createChartData = (data: any[], label: string) => ({
  labels: data.map(item => {
    const date = new Date(item[0]); 
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit'}); 
  }),
  datasets: [
    {
      label,
      data: data.map(item => item[1]), 
      borderColor: 'rgba(73, 166, 216, 1)',
      backgroundColor: 'rgba(250, 251, 254, 0.2)',
    },
  ],
});

const ResourceUtilizationAccordion: React.FC = () => {
  const { t } = useTranslation();
  return (
    <Accordion title={t('accordion.resource')}>
      <div className="accordion-subtitle">{t('accordion.subtitle_resource')}</div>
      {resourceData ? (
        <div className="accordion-content">
          <div className="chart-row">
            <div className="chart-container">
              <div className="accordion-content">{t('accordion.cpuUtilization') || "CPU Utilization"}</div>
              <Line className="chart" data={createChartData(resourceData.cpu_utilization, t('accordion.cpuUtilization') || 'CPU Utilization')} />
            </div>
            <div className="chart-container">
              <div className="accordion-content">{t('accordion.gpuUtilization') || "GPU Utilization"}</div>
              <Line className="chart" data={createChartData(resourceData.gpu_utilization.map((item: any[]) => [item[0], item[4]]), t('accordion.gpuUtilization') || 'GPU Utilization')} />
            </div>
          </div>
          <div className="chart-row">
            <div className="chart-container">
              <div className="accordion-content">{t('accordion.memoryUtilization') || "Memory Utilization"}</div>
              <Line className="chart" data={createChartData(resourceData.memory.map((item: any[]) => [item[0], item[4]]), t('accordion.memoryUtilization') || 'Memory Utilization')} />
            </div>
            <div className="chart-container">
              <div className="accordion-content">{t('accordion.powerUtilization') || "Power Utilization"}</div>
              <Line className="chart" data={createChartData(resourceData.power, t('accordion.powerUtilization') || 'Power Utilization')} />
            </div>
          </div>
        </div>
      ) : (
        <p className="accordion-content">{t('accordion.loadingResource') || "Loading resource data..."}</p>
      )}
    </Accordion>
  );
};

export default ResourceUtilizationAccordion;