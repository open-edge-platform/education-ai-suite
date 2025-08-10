const WebSocket = require("ws");

const PORT = 8080; // Port for the WebSocket server
const wss = new WebSocket.Server({ port: PORT });

console.log(`WebSocket server is running on ws://localhost:${PORT}`);

// Mock data to send to clients
const mockData = [
  { text: "Hello, welcome to the Smart Classroom.", timestamp: "00:00", speaker: "Speaker 1" },
  { text: "Today we will discuss AI and its applications.", timestamp: "00:05", speaker: "Speaker 2" },
  { text: "Artificial Intelligence is transforming industries.", timestamp: "00:10", speaker: "Speaker 1" },
  { text: "Let's dive deeper into machine learning.", timestamp: "00:15", speaker: "Speaker 2" },
];

wss.on("connection", (ws) => {
  console.log("Client connected.");

  let index = 0;

  // Send mock data to the client every 2 seconds
  const interval = setInterval(() => {
    if (index < mockData.length) {
      ws.send(JSON.stringify(mockData[index]));
      index++;
    } else {
      clearInterval(interval);
      ws.close();
    }
  }, 2000);

  ws.on("close", () => {
    console.log("Client disconnected.");
  });
});