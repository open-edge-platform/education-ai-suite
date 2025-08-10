import { useSelector } from "react-redux";
import type { RootState } from "../../redux/store";
import BubbleList from "../common/BubbleList";
import "./TranscriptsTab.scss";

const TranscriptsTab = () => {
  const chunks = useSelector((state: RootState) => state.transcript.chunks);

  return (
    <div className="transcripts-tab">
      <h2>Transcripts</h2>
      <BubbleList items={chunks} />
    </div>
  );
};

export default TranscriptsTab;