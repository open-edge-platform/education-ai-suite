import { useEffect } from "react";
import { useAppDispatch, useAppSelector } from "../../redux/hooks";
import { getResourceMetrics } from "../../services/api";
import { setMetrics, resetMetrics } from "../../redux/slices/resourceSlice";

const MetricsPoller: React.FC = () => {
  const sessionId = useAppSelector(s => s.file.sessionId);
  const aiProcessing = useAppSelector(s => s.ui.aiProcessing);
  const dispatch = useAppDispatch();

  useEffect(() => {
    if (!sessionId || !aiProcessing) {
      dispatch(resetMetrics());
      return;
    }
    let cancelled = false;
    const poll = () => {
      if (!cancelled) {
        getResourceMetrics(sessionId).then(metrics => {
          dispatch(setMetrics(metrics));
        });
        setTimeout(poll, 3000);
      }
    };
    poll();
    return () => { cancelled = true; };
  }, [sessionId, aiProcessing, dispatch]);

  return null;
};

export default MetricsPoller;