import React, { useEffect, useState } from 'react';
import { Line } from 'react-chartjs-2';
import { Chart, registerables } from 'chart.js';
import Accordion from '../common/Accordion'; 
import '../../assets/css/RightPanel.css'
import { useTranslation } from 'react-i18next';
import { getResourceMetrics } from '../../services/api';

import { useAppSelector } from '../../redux/hooks';
Chart.register(...registerables);

type GPUMetricKey = 'shared_memory_mb' | '3D_utilization_percent' | 'VideoDecode_utilization_percent' | 'VideoProcessing_utilization_percent' | 'Compute_utilization_percent';

interface GPUMetricConfig {
  index: number;
  color: string;
  label: string;
  yAxis: 'y' | 'y1';
  shortLabel: string;
}

type GPUMetricsConfig = Record<GPUMetricKey, GPUMetricConfig>;

interface ResourceAccordionProps {
  sessionId?: string;
}

const ResourceUtilizationAccordion: React.FC<ResourceAccordionProps> = ({ sessionId }) => {
  const { t } = useTranslation();
  const [resourceData, setResourceData] = useState<any>({
    cpu_utilization: [],
    gpu_utilization: [],
    memory: [],
    power: [],
  });
  const [selectedGPUMetrics, setSelectedGPUMetrics] = useState<GPUMetricKey[]>([
    '3D_utilization_percent', 
    'Compute_utilization_percent'
  ]);

useEffect(() => {
    if (!sessionId) {
      console.warn('No sessionId provided to ResourceUtilizationAccordion');
      return;
    }

    const interval = setInterval(async () => {
      try {
        const data = await getResourceMetrics(sessionId);
        setResourceData((prev: { cpu_utilization: any; gpu_utilization: any; memory: any; power: any; }) => ({
          cpu_utilization: [...prev.cpu_utilization, ...data.cpu_utilization].slice(-10),
          gpu_utilization: [...prev.gpu_utilization, ...data.gpu_utilization].slice(-10),
          memory: [...prev.memory, ...data.memory].slice(-10),
          power: [...prev.power, ...data.power].slice(-10),
        }));
      } catch (err) {
        console.error('Failed to fetch metrics:', err);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [sessionId]);

  const formatTimeLabel = (timestamp: string | number, _index: number, isFirstLabel: boolean = false) => {
    const date = new Date(timestamp);
    if (isFirstLabel) {
      return date.toLocaleTimeString([], { 
        hour: '2-digit', 
        minute: '2-digit', 
        second: '2-digit',
        hour12: false  
      });
    } else {
      return date.toLocaleTimeString([], { 
        minute: '2-digit', 
        second: '2-digit',
        hour12: false 
      });
    }
  };

  const getDisplayDataPoints = (data: any[], maxPoints: number = 10) => {
    if (data.length <= maxPoints) {
      return data;
    }
    const step = Math.floor(data.length / maxPoints);
    const result = [];
    for (let i = 0; i < data.length; i += step) {
      result.push(data[i]);
    }
    if (result[result.length - 1] !== data[data.length - 1]) {
      result.push(data[data.length - 1]);
    }
    return result.slice(0, maxPoints);
  };

  const calculateYAxisRange = (values: number[]) => {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min;
    const padding = range * 0.1;
    const adjustedMin = Math.max(0, min - padding); 
    const adjustedMax = max + padding;
    
    return {
      min: Math.floor(adjustedMin),
      max: Math.ceil(adjustedMax)
    };
  };

  const createChartData = (data: any[], label: string) => {
    const displayData = getDisplayDataPoints(data, 10);
    
    return {
      labels: displayData.map((item, index) => 
        formatTimeLabel(item[0], index, index === 0)
      ),
      datasets: [
        {
          label: label,
          data: displayData.map(item => item[1]), 
          borderColor: 'rgba(73, 166, 216, 1)',
          backgroundColor: 'rgba(250, 251, 254, 0.2)',
          borderWidth: 2,
          pointRadius: 1,
          pointHoverRadius: 4,
        },
      ],
    };
  };

  const gpuMetricsConfig: GPUMetricsConfig = {
    'shared_memory_mb': { 
      index: 3, 
      color: 'rgba(255, 99, 132, 1)', 
      label: 'Memory (GB)',
      yAxis: 'y1',
      shortLabel: 'Mem'
    },
    '3D_utilization_percent': { 
      index: 4, 
      color: 'rgba(54, 162, 235, 1)', 
      label: '3D (%)', 
      yAxis: 'y',
      shortLabel: '3D'
    },
    'VideoDecode_utilization_percent': { 
      index: 6, 
      color: 'rgba(255, 205, 86, 1)', 
      label: 'Video Dec (%)', 
      yAxis: 'y',
      shortLabel: 'VDec'
    },
    'VideoProcessing_utilization_percent': { 
      index: 7, 
      color: 'rgba(75, 192, 192, 1)', 
      label: 'Video Proc (%)', 
      yAxis: 'y',
      shortLabel: 'VProc'
    },
    'Compute_utilization_percent': { 
      index: 9, 
      color: 'rgba(153, 102, 255, 1)', 
      label: 'Compute (%)', 
      yAxis: 'y',
      shortLabel: 'Comp'
    },
  };

  const createGPUChartData = (data: any[]) => {
    const displayData = getDisplayDataPoints(data, 10);
    
    return {
      labels: displayData.map((item, index) => 
        formatTimeLabel(item[0], index, index === 0)
      ),
      datasets: selectedGPUMetrics.map(metric => {
        const config = gpuMetricsConfig[metric];
        
        return {
          label: config.shortLabel,
          data: displayData.map(item => {
            return metric === 'shared_memory_mb' ? item[config.index] / 1024 : item[config.index];
          }),
          borderColor: config.color,
          backgroundColor: config.color.replace('1)', '0.1)'),
          borderWidth: 2,
          pointRadius: 1,
          pointHoverRadius: 4,
          yAxisID: config.yAxis,
          tension: 0.1,
        };
      }),
    };
  };

  const createAdaptiveChartOptions = (data: any[], isGPUChart: boolean = false, _scaleBy: number = 1) => {
    let yAxisRange = { min: 0, max: 100 };
    let y1AxisRange = { min: 0, max: 1000 };

    if (isGPUChart) {
      const percentageValues: number[] = [];
      const memoryValues: number[] = [];

      selectedGPUMetrics.forEach(metric => {
        const config = gpuMetricsConfig[metric];
        const values = data.map(item => item[config.index]).filter(val => val != null);
        
        if (config.yAxis === 'y') {
          percentageValues.push(...values);
        } else if (metric === 'shared_memory_mb') {
          memoryValues.push(...values.map(val => val / 1024));
        }
      });

      if (percentageValues.length > 0) {
        yAxisRange = calculateYAxisRange(percentageValues);
      }
      if (memoryValues.length > 0) {
        y1AxisRange = calculateYAxisRange(memoryValues);
      }
    } else {
      const values = data.map(item => item[1]).filter(val => val != null);
      if (values.length > 0) {
        yAxisRange = calculateYAxisRange(values);
      }
    }

    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index' as const,
        intersect: false,
      },
      elements: {
        point: {
          radius: 1,
          hoverRadius: 4,
        },
        line: {
          borderWidth: 2,
        }
      },
      scales: {
        x: {
          display: true,
          grid: {
            display: false,
          },
          ticks: {
            maxTicksLimit: 10,
            font: {
              size: 10,
            }
          }
        },
        y: {
          type: 'linear' as const,
          display: !isGPUChart || selectedGPUMetrics.some(m => gpuMetricsConfig[m].yAxis === 'y'),
          position: 'left' as const,
          min: yAxisRange.min,
          max: yAxisRange.max,
          grid: {
            color: 'rgba(0,0,0,0.1)',
          },
          ticks: {
            maxTicksLimit: 5,
            font: {
              size: 10,
            }
          }
        },
        y1: {
          type: 'linear' as const,
          display: isGPUChart && selectedGPUMetrics.includes('shared_memory_mb'),
          position: 'right' as const,
          min: y1AxisRange.min,
          max: y1AxisRange.max,
          grid: {
            drawOnChartArea: false,
          },
          ticks: {
            maxTicksLimit: 5,
            font: {
              size: 10,
            },
            callback: function(value: any) {
              return value + ' GB';
            }
          }
        },
      },
      plugins: {
        legend: {
          display: isGPUChart ? false : true, 
          position: 'top' as const,
          labels: {
            usePointStyle: true,
            pointStyle: 'line',
            font: {
              size: 10,
            },
            padding: 10,
          }
        },
        tooltip: {
          titleFont: {
            size: 11,
          },
          bodyFont: {
            size: 10,
          },
          callbacks: {
            label: function(context: any) {
              const datasetLabel = context.dataset.label || '';
              const value = context.parsed.y;
              if (datasetLabel === 'Mem') {
                return `${datasetLabel}: ${value.toFixed(2)} GB`;
              } else {
                return `${datasetLabel}: ${value.toFixed(1)}%`;
              }
            }
          }
        }
      },
      layout: {
        padding: {
          top: 5,
          bottom: 5,
          left: 5,
          right: 5,
        }
      }
    };
  };

  const handleMetricToggle = (metric: GPUMetricKey) => {
    setSelectedGPUMetrics(prev => 
      prev.includes(metric) 
        ? prev.filter(m => m !== metric)
        : [...prev, metric]
    );
  };


  const hasData = resourceData.cpu_utilization.length > 0 || 
                  resourceData.gpu_utilization.length > 0 || 
                  resourceData.memory.length > 0 || 
                  resourceData.power.length > 0;
  // const resourceData = useAppSelector(s => s.resource.metrics);

  return (
    <Accordion title={t('accordion.resource')}>
      {hasData ? (
        <div className="accordion-content">
          <div className="charts-grid">
            <div className="chart-row">
              <div className="chart-container-half">
                <h4 className="chart-title">{t('CPU Utilization')}</h4>
                <div className="chart-wrapper">
                  {resourceData.cpu_utilization.length > 0 ? (
                    <Line 
                      className="chart" 
                      data={createChartData(resourceData.cpu_utilization, 'CPU %')} 
                      options={createAdaptiveChartOptions(getDisplayDataPoints(resourceData.cpu_utilization, 10))}
                    />
                  ) : (
                    <div className="no-data-message">{t('No CPU data available')}</div>
                  )}
                </div>
              </div>
              
              <div className="chart-container-half">
                <div className="gpu-header">
                  <h4 className="chart-title">{t('GPU Utilization')}</h4>

                  <div className="gpu-metrics-checkboxes">
                    {(Object.entries(gpuMetricsConfig) as [GPUMetricKey, GPUMetricConfig][]).map(([key, config]) => (
                      <label
                        key={key}
                        className="gpu-metric-checkbox"
                        style={{ '--metric-color': config.color } as React.CSSProperties}
                      >
                        <input
                          type="checkbox"
                          checked={selectedGPUMetrics.includes(key)}
                          onChange={() => handleMetricToggle(key)}
                          className="checkbox-input"
                        />
                        <span className="checkbox-label">
                          {config.shortLabel}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
                
                <div className="chart-wrapper">
                  {resourceData.gpu_utilization.length > 0 ? (
                    <Line 
                      className="chart" 
                      data={createGPUChartData(resourceData.gpu_utilization)} 
                      options={createAdaptiveChartOptions(getDisplayDataPoints(resourceData.gpu_utilization, 10), true)}
                    />
                  ) : (
                    <div className="no-data-message">{t('No GPU data available')}</div>
                  )}
                </div>
              </div>
            </div>
            <div className="chart-row">
              <div className="chart-container-half">
                <h4 className="chart-title">{t('Memory Utilization')}</h4>
                <div className="chart-wrapper">
                  {resourceData.memory.length > 0 ? (
                    <Line 
                      className="chart" 
                      data={createChartData(resourceData.memory.map((item: any[]) => [item[0], item[4]]), 'Memory %')} 
                      options={createAdaptiveChartOptions(getDisplayDataPoints(resourceData.memory.map((item: any[]) => [item[0], item[4]]), 10))}
                    />
                  ) : (
                    <div className="no-data-message">{t('No Memory data available')}</div>
                  )}
                </div>
              </div>
              
              <div className="chart-container-half">
                <h4 className="chart-title">{t('Power Utilization')}</h4>
                <div className="chart-wrapper">
                  {resourceData.power.length > 0 ? (
                    <Line 
                      className="chart" 
                      data={createChartData(resourceData.power, 'Power')} 
                      options={createAdaptiveChartOptions(getDisplayDataPoints(resourceData.power, 10))}
                    />
                  ) : (
                    <div className="no-data-message">{t('No Power data available')}</div>
                  )}
                </div>
              </div>
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