import "./BubbleList.scss";

interface BubbleItemProps {
  text: string;
  timestamp?: string;
  speaker?: string;
}

const BubbleItem = ({ text, timestamp, speaker }: BubbleItemProps) => {
  return (
    <div className="bubble-item" role="listitem">
      {timestamp && <span className="timestamp">{timestamp}</span>}
      {speaker && <span className="speaker">{speaker}: </span>}
      <span className="text">{text}</span>
    </div>
  );
};

export default BubbleItem;