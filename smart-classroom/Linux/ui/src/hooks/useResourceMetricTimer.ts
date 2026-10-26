import { useEffect, useRef } from 'react';
import { useAppDispatch, useAppSelector } from '../redux/hooks';
import { setMonitoringActive, setMonitoringPaused } from '../redux/slices/uiSlice';
import { RESOURCE_METRIC_DURATION_MS } from '../utils/resourceMetricConfig';

/**
 * Automatically stops the resource utilization graph from updating after
 * RESOURCE_METRIC_DURATION_MS. There is no server-side start/stop: the
 * metrics-collector sidecar collects continuously, so this is purely a
 * client-side switch that gates MetricsPoller's polling loop.
 * Sets monitoringPaused=true in Redux when the duration expires.
 * Provides a resumeMonitoring() function to resume polling and reset the timer.
 */
export function useResourceMetricTimer() {
  const dispatch = useAppDispatch();
  const monitoringActive = useAppSelector((s) => s.ui.monitoringActive);
  const sessionId = useAppSelector((s) => s.ui.sessionId);
  const timerRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => {
    if (monitoringActive) {
      clearTimer();
      timerRef.current = window.setTimeout(() => {
        dispatch(setMonitoringActive(false));
        dispatch(setMonitoringPaused(true));
      }, RESOURCE_METRIC_DURATION_MS);
    } else {
      clearTimer();
    }

    return clearTimer;
  }, [monitoringActive, dispatch]);

  const resumeMonitoring = () => {
    if (!sessionId) return;
    dispatch(setMonitoringPaused(false));
    dispatch(setMonitoringActive(true));
  };

  return { resumeMonitoring };
}
