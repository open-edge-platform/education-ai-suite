import { useSelector } from "react-redux";
import type { RootState } from "../../redux/store";
import BubbleList from "../common/BubbleList";
import "./AISummaryTab.scss";

const SummaryTab = () => {
  const summaries = useSelector((state: RootState) => state.summary.items);

  return (
    <div className="summary-tab">
      <h2>Summary</h2>
      <BubbleList items={summaries} />
    </div>
  );
};

export default SummaryTab;